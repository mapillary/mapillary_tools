from __future__ import annotations

import io
import typing as T

from .. import geo
from ..mp4 import (
    construct_mp4_parser as cparser,
    mp4_sample_parser as sample_parser,
    simple_mp4_builder as builder,
)

from . import camm_parser


def _build_camm_sample(measurement: camm_parser.TelemetryMeasurement) -> bytes:
    if camm_parser.GoProGPSSampleEntry.serializable(measurement):
        return camm_parser.GoProGPSSampleEntry.serialize(measurement)

    for sample_entry_cls in camm_parser.SAMPLE_ENTRY_CLS_BY_CAMM_TYPE.values():
        if sample_entry_cls.serializable(measurement):
            return sample_entry_cls.serialize(measurement)

    raise ValueError(f"Unsupported measurement type {type(measurement)}")


def _create_edit_list_from_points(
    tracks: T.Sequence[T.Sequence[geo.Point]],
    movie_timescale: int,
    media_timescale: int,
) -> builder.BoxDict:
    entries: list[dict] = []

    non_empty_tracks = [track for track in tracks if track]

    for idx, track in enumerate(non_empty_tracks):
        assert 0 <= track[0].time, f"expect non-negative point time but got {track[0]}"
        assert track[0].time <= track[-1].time, (
            f"expect points to be sorted but got first point {track[0]} and last point {track[-1]}"
        )

        if idx == 0:
            if 0 < track[0].time:
                segment_duration = int(track[0].time * movie_timescale)
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
            media_time = int(track[0].time * media_timescale)
            segment_duration = int((track[-1].time - track[0].time) * movie_timescale)
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


def convert_telemetry_to_raw_samples(
    measurements: T.Sequence[camm_parser.TelemetryMeasurement],
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


def camm_sample_generator2(camm_info: camm_parser.CAMMInfo):
    def _f(
        fp: T.BinaryIO,
        moov_children: list[builder.BoxDict],
    ) -> T.Generator[io.IOBase, None, None]:
        movie_timescale = builder.find_movie_timescale(moov_children)
        # Make sure the precision of timedeltas not lower than 0.001 (1ms)
        media_timescale = max(1000, movie_timescale)

        # Multiplex points for creating elst
        track: list[geo.Point] = [
            *(camm_info.gps or []),
            *(camm_info.mini_gps or []),
        ]
        track.sort(key=lambda p: p.time)
        if track and track[0].time < 0:
            track = [p for p in track if p.time >= 0]
        elst = _create_edit_list_from_points([track], movie_timescale, media_timescale)

        # Multiplex telemetry measurements
        measurements: list[camm_parser.TelemetryMeasurement] = [
            *(camm_info.gps or []),
            *(camm_info.mini_gps or []),
            *(camm_info.accl or []),
            *(camm_info.gyro or []),
            *(camm_info.magn or []),
        ]
        measurements.sort(key=lambda m: m.time)
        if measurements and measurements[0].time < 0:
            measurements = [m for m in measurements if m.time >= 0]

        # Serialize the telemetry measurements into MP4 samples
        camm_samples = list(
            convert_telemetry_to_raw_samples(measurements, media_timescale)
        )

        camm_trak = create_camm_trak(camm_samples, media_timescale)

        if T.cast(T.Dict, elst["data"])["entries"]:
            T.cast(T.List[builder.BoxDict], camm_trak["data"]).append(
                {
                    "type": b"edts",
                    "data": [elst],
                }
            )
        moov_children.append(camm_trak)

        udta_data: list[builder.BoxDict] = []
        if camm_info.make:
            udta_data.append(
                {
                    "type": b"@mak",
                    "data": camm_info.make.encode("utf-8"),
                }
            )
        if camm_info.model:
            udta_data.append(
                {
                    "type": b"@mod",
                    "data": camm_info.model.encode("utf-8"),
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
