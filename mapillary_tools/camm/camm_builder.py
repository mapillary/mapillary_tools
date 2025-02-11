import io
import typing as T

from .. import geo, telemetry, types
from ..mp4 import (
    construct_mp4_parser as cparser,
    mp4_sample_parser as sample_parser,
    simple_mp4_builder as builder,
)

from . import camm_parser


TelemetryMeasurement = T.Union[
    geo.Point,
    telemetry.TelemetryMeasurement,
]


def _build_camm_sample(measurement: TelemetryMeasurement) -> bytes:
    if isinstance(measurement, geo.Point):
        return camm_parser.CAMMSampleData.build(
            {
                "type": camm_parser.CAMMType.MIN_GPS.value,
                "data": [
                    measurement.lat,
                    measurement.lon,
                    -1.0 if measurement.alt is None else measurement.alt,
                ],
            }
        )
    elif isinstance(measurement, telemetry.AccelerationData):
        # Accelerometer reading in meters/second^2 along XYZ axes of the camera.
        return camm_parser.CAMMSampleData.build(
            {
                "type": camm_parser.CAMMType.ACCELERATION.value,
                "data": [
                    measurement.x,
                    measurement.y,
                    measurement.z,
                ],
            }
        )
    elif isinstance(measurement, telemetry.GyroscopeData):
        # Gyroscope signal in radians/seconds around XYZ axes of the camera. Rotation is positive in the counterclockwise direction.
        return camm_parser.CAMMSampleData.build(
            {
                "type": camm_parser.CAMMType.GYRO.value,
                "data": [
                    measurement.x,
                    measurement.y,
                    measurement.z,
                ],
            }
        )
    elif isinstance(measurement, telemetry.MagnetometerData):
        # Ambient magnetic field.
        return camm_parser.CAMMSampleData.build(
            {
                "type": camm_parser.CAMMType.MAGNETIC_FIELD.value,
                "data": [
                    measurement.x,
                    measurement.y,
                    measurement.z,
                ],
            }
        )
    else:
        raise ValueError(f"unexpected measurement type {type(measurement)}")


def _create_edit_list_from_points(
    point_segments: T.Sequence[T.Sequence[geo.Point]],
    movie_timescale: int,
    media_timescale: int,
) -> builder.BoxDict:
    entries: T.List[T.Dict] = []

    non_empty_point_segments = [points for points in point_segments if points]

    for idx, points in enumerate(non_empty_point_segments):
        assert 0 <= points[0].time, (
            f"expect non-negative point time but got {points[0]}"
        )
        assert points[0].time <= points[-1].time, (
            f"expect points to be sorted but got first point {points[0]} and last point {points[-1]}"
        )

        if idx == 0:
            if 0 < points[0].time:
                segment_duration = int(points[0].time * movie_timescale)
                # put an empty edit list entry to skip the initial gap
                entries.append(
                    {
                        # If this field is set to –1, it is an empty edit
                        "media_time": -1,
                        "segment_duration": segment_duration,
                        "media_rate_integer": 1,
                        "media_rate_fraction": 0,
                    }
                )
        else:
            media_time = int(points[0].time * media_timescale)
            segment_duration = int((points[-1].time - points[0].time) * movie_timescale)
            entries.append(
                {
                    "media_time": media_time,
                    "segment_duration": segment_duration,
                    "media_rate_integer": 1,
                    "media_rate_fraction": 0,
                }
            )

    return {
        "type": b"elst",
        "data": {
            "entries": entries,
        },
    }


def _multiplex(
    points: T.Sequence[geo.Point],
    measurements: T.Optional[T.List[telemetry.TelemetryMeasurement]] = None,
) -> T.List[TelemetryMeasurement]:
    mutiplexed: T.List[TelemetryMeasurement] = [*points, *(measurements or [])]
    mutiplexed.sort(key=lambda m: m.time)

    return mutiplexed


def convert_telemetry_to_raw_samples(
    measurements: T.Sequence[TelemetryMeasurement],
    timescale: int,
) -> T.Generator[sample_parser.RawSample, None, None]:
    for idx, measurement in enumerate(measurements):
        camm_sample_data = _build_camm_sample(measurement)

        if idx + 1 < len(measurements):
            timedelta = int((measurements[idx + 1].time - measurement.time) * timescale)
        else:
            timedelta = 0

        assert 0 <= timedelta <= builder.UINT32_MAX, (
            f"expected timedelta {timedelta} between {measurements[idx]} and {measurements[idx + 1]} with timescale {timescale} to be <= UINT32_MAX"
        )

        yield sample_parser.RawSample(
            # will update later
            description_idx=1,
            # will update later
            offset=0,
            size=len(camm_sample_data),
            timedelta=timedelta,
            composition_offset=0,
            is_sync=True,
        )


_STBLChildrenBuilderConstruct = cparser.Box32ConstructBuilder(
    T.cast(cparser.SwitchMapType, cparser.CMAP[b"stbl"])
)


def _create_camm_stbl(
    raw_samples: T.Iterable[sample_parser.RawSample],
) -> builder.BoxDict:
    descriptions = [
        {
            "format": b"camm",
            "data_reference_index": 1,
            "data": b"",
        }
    ]

    stbl_children_boxes = builder.build_stbl_from_raw_samples(descriptions, raw_samples)

    stbl_data = _STBLChildrenBuilderConstruct.build_boxlist(stbl_children_boxes)
    return {
        "type": b"stbl",
        "data": stbl_data,
    }


def create_camm_trak(
    raw_samples: T.Sequence[sample_parser.RawSample],
    media_timescale: int,
) -> builder.BoxDict:
    stbl = _create_camm_stbl(raw_samples)

    hdlr: builder.BoxDict = {
        "type": b"hdlr",
        "data": {
            "handler_type": b"camm",
            "name": "CameraMetadataMotionHandler",
        },
    }

    media_duration = sum(s.timedelta for s in raw_samples)
    assert media_timescale <= builder.UINT64_MAX

    # Media Header Box
    mdhd: builder.BoxDict = {
        "type": b"mdhd",
        "data": {
            # use 64-bit version
            "version": 1,
            # TODO: find timestamps from mvhd?
            # do not set dynamic timestamps (e.g. time.time()) here because we'd like to
            # make sure the md5 of the new mp4 file unchanged
            "creation_time": 0,
            "modification_time": 0,
            "timescale": media_timescale,
            "duration": media_duration,
            "language": 21956,
        },
    }

    dinf: builder.BoxDict = {
        "type": b"dinf",
        "data": [
            # self reference dref box
            {
                "type": b"dref",
                "data": {
                    "entries": [
                        {
                            "type": b"url ",
                            "data": {
                                "flags": 1,
                                "data": b"",
                            },
                        }
                    ],
                },
            }
        ],
    }

    minf: builder.BoxDict = {
        "type": b"minf",
        "data": [
            dinf,
            stbl,
        ],
    }

    tkhd: builder.BoxDict = {
        "type": b"tkhd",
        "data": {
            # use 32-bit version of the box
            "version": 0,
            # TODO: find timestamps from mvhd?
            # do not set dynamic timestamps (e.g. time.time()) here because we'd like to
            # make sure the md5 of the new mp4 file unchanged
            "creation_time": 0,
            "modification_time": 0,
            # will update the track ID later
            "track_ID": 0,
            # If the duration of this track cannot be determined then duration is set to all 1s (32-bit maxint).
            "duration": 0xFFFFFFFF,
            "layer": 0,
        },
    }

    mdia: builder.BoxDict = {
        "type": b"mdia",
        "data": [
            mdhd,
            hdlr,
            minf,
        ],
    }

    return {
        "type": b"trak",
        "data": [
            tkhd,
            mdia,
        ],
    }


def camm_sample_generator2(
    video_metadata: types.VideoMetadata,
    telemetry_measurements: T.Optional[T.List[telemetry.TelemetryMeasurement]] = None,
):
    def _f(
        fp: T.BinaryIO,
        moov_children: T.List[builder.BoxDict],
    ) -> T.Generator[io.IOBase, None, None]:
        movie_timescale = builder.find_movie_timescale(moov_children)
        # make sure the precision of timedeltas not lower than 0.001 (1ms)
        media_timescale = max(1000, movie_timescale)

        # points with negative time are skipped
        # TODO: interpolate first point at time == 0
        # TODO: measurements with negative times should be skipped too
        points = [point for point in video_metadata.points if point.time >= 0]

        measurements = _multiplex(points, telemetry_measurements)
        camm_samples = list(
            convert_telemetry_to_raw_samples(measurements, media_timescale)
        )
        camm_trak = create_camm_trak(camm_samples, media_timescale)
        elst = _create_edit_list_from_points([points], movie_timescale, media_timescale)
        if T.cast(T.Dict, elst["data"])["entries"]:
            T.cast(T.List[builder.BoxDict], camm_trak["data"]).append(
                {
                    "type": b"edts",
                    "data": [elst],
                }
            )
        moov_children.append(camm_trak)

        udta_data: T.List[builder.BoxDict] = []
        if video_metadata.make:
            udta_data.append(
                {
                    "type": b"@mak",
                    "data": video_metadata.make.encode("utf-8"),
                }
            )
        if video_metadata.model:
            udta_data.append(
                {
                    "type": b"@mod",
                    "data": video_metadata.model.encode("utf-8"),
                }
            )
        if udta_data:
            moov_children.append(
                {
                    "type": b"udta",
                    "data": udta_data,
                }
            )

        # if yield, the moov_children will not be modified
        return (
            io.BytesIO(_build_camm_sample(measurement)) for measurement in measurements
        )

    return _f
