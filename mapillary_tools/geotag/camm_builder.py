import io
import typing as T

from .. import geo, utils

from . import (
    blackvue_parser,
    camm_parser,
    gpmf_parser,
    simple_mp4_builder as builder,
    simple_mp4_parser as parser,
)
from .simple_mp4_builder import BoxDict


def build_camm_sample(point: geo.Point) -> bytes:
    return camm_parser.CAMMSampleData.build(
        {
            "type": camm_parser.CAMMType.MIN_GPS.value,
            "data": [
                point.lat,
                point.lon,
                -1.0 if point.alt is None else point.alt,
            ],
        }
    )


def _create_edit_list(
    point_segments: T.Sequence[T.Sequence[geo.Point]],
    movie_timescale: int,
    media_timescale: int,
) -> BoxDict:
    entries: T.List[T.Dict] = []

    for idx, points in enumerate(point_segments):
        if not points:
            entries = [
                {
                    "media_time": 0,
                    "segment_duration": 0,
                    "media_rate_integer": 1,
                    "media_rate_fraction": 0,
                }
            ]
            break

        assert (
            0 <= points[0].time
        ), f"expect non-negative point time but got {points[0]}"
        assert (
            points[0].time <= points[-1].time
        ), f"expect points to be sorted but got first point {points[0]} and last point {points[-1]}"

        if idx == 0:
            if 0 < points[0].time:
                segment_duration = int(points[0].time * movie_timescale)
                entries.append(
                    {
                        "media_time": -1,
                        "segment_duration": segment_duration,
                        "media_rate_integer": 1,
                        "media_rate_fraction": 0,
                    }
                )
        else:
            assert point_segments[-1][-1].time <= points[0].time
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


def convert_points_to_raw_samples(
    points: T.Sequence[geo.Point], timescale: int
) -> T.Generator[parser.RawSample, None, None]:
    for idx, point in enumerate(points):
        camm_sample_data = build_camm_sample(point)

        if idx + 1 < len(points):
            timedelta = int((points[idx + 1].time - point.time) * timescale)
        else:
            timedelta = 0
        assert (
            0 <= timedelta <= builder.UINT32_MAX
        ), f"expected timedelta {timedelta} between {points[idx]} and {points[idx + 1]} with timescale {timescale} to be <= UINT32_MAX"

        yield parser.RawSample(
            # will update later
            description_idx=1,
            # will update later
            offset=0,
            size=len(camm_sample_data),
            timedelta=timedelta,
            is_sync=True,
        )


def _create_camm_stbl(raw_samples: T.Iterable[parser.RawSample]) -> BoxDict:
    descriptions = [
        {
            "format": b"camm",
            "data_reference_index": 1,
            "data": b"",
        }
    ]

    stbl_children_boxes = builder.build_stbl_from_raw_samples(descriptions, raw_samples)

    stbl_data = builder.FullBoxStruct32.BoxList.build(stbl_children_boxes)
    return {
        "type": b"stbl",
        "data": stbl_data,
    }


_SELF_REFERENCE_DREF_BOX_DATA: bytes = builder.FullBoxStruct32.Box.build(
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
)


def create_camm_trak(
    raw_samples: T.Sequence[parser.RawSample],
    media_timescale: int,
) -> BoxDict:
    stbl = _create_camm_stbl(raw_samples)

    hdlr = {
        "type": b"hdlr",
        "data": {
            "handler_type": b"camm",
            "name": "CameraMetadataMotionHandler",
        },
    }

    media_duration = sum(s.timedelta for s in raw_samples)
    assert media_timescale <= builder.UINT64_MAX

    # Media Header Box
    mdhd = {
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

    dinf: BoxDict = {
        "type": b"dinf",
        "data": _SELF_REFERENCE_DREF_BOX_DATA,
    }

    minf: BoxDict = {
        "type": b"minf",
        "data": [
            dinf,
            stbl,
        ],
    }

    tkhd: BoxDict = {
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

    mdia: BoxDict = {
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


def extract_points(
    fp: T.BinaryIO,
    file_types: T.Optional[T.Set[utils.FileType]] = None,
) -> T.Tuple[T.Optional[utils.FileType], T.List[geo.Point]]:
    start_offset = fp.tell()

    if file_types is None or utils.FileType.CAMM in file_types:
        try:
            points = camm_parser.extract_points(fp)
        except (parser.BoxNotFoundError, parser.RangeError):
            points = []
        if points:
            return utils.FileType.CAMM, points

    if file_types is None or utils.FileType.GOPRO in file_types:
        fp.seek(start_offset)
        try:
            points_with_fix = gpmf_parser.extract_points(fp)
        except (parser.BoxNotFoundError, parser.RangeError):
            points = []
        if points_with_fix:
            return utils.FileType.GOPRO, T.cast(T.List[geo.Point], points_with_fix)

    if file_types is None or utils.FileType.BLACKVUE in file_types:
        fp.seek(start_offset)
        try:
            points = blackvue_parser.extract_points(fp)
        except (parser.BoxNotFoundError, parser.RangeError):
            points = []
        if points:
            return utils.FileType.BLACKVUE, points

    return None, []


def camm_sample_generator2(points: T.Sequence[geo.Point]):
    def _f(
        fp: T.BinaryIO,
        moov_children: T.List[BoxDict],
    ) -> T.Generator[io.IOBase, None, None]:
        movie_timescale = builder.find_movie_timescale(moov_children)
        # make sure the precision of timedeltas not lower than 0.001 (1ms)
        media_timescale = max(1000, movie_timescale)
        camm_samples = list(convert_points_to_raw_samples(points, media_timescale))
        camm_trak = create_camm_trak(camm_samples, media_timescale)
        elst = _create_edit_list([points], movie_timescale, media_timescale)
        if T.cast(T.Dict, elst["data"])["entries"]:
            T.cast(T.List[BoxDict], camm_trak["data"]).append(
                {
                    "type": b"edts",
                    "data": [elst],
                }
            )
        moov_children.append(camm_trak)

        # if yield, the moov_children will not be modified
        return (io.BytesIO(build_camm_sample(point)) for point in points)

    return _f


def camm_sample_generator(
    fp: T.BinaryIO,
    moov_children: T.List[BoxDict],
) -> T.Iterator[io.IOBase]:
    fp.seek(0)
    _, points = extract_points(fp)
    if not points:
        raise ValueError("no points found")

    return camm_sample_generator2(points)(fp, moov_children)
