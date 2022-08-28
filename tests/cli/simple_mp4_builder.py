import argparse
import io
import itertools
import pathlib
import time
import typing as T
from dataclasses import dataclass

import mapillary_tools.geo as geo
from mapillary_tools.geotag import (
    blackvue_utils,
    camm_builder,
    camm_parser,
    gpmf_parser,
    simple_mp4_builder as builder,
    simple_mp4_parser as parser,
)
from mapillary_tools.geotag.simple_mp4_builder import BoxDict


def _find_box_at_pathx(
    box: T.Union[T.Iterable[BoxDict], BoxDict], path: T.Sequence[bytes]
) -> BoxDict:
    if not path:
        raise ValueError(f"box at path {path} not found")
    boxes: T.Iterable[BoxDict]
    if isinstance(box, dict):
        boxes = [T.cast(BoxDict, box)]
    else:
        boxes = box
    for box in boxes:
        if box["type"] == path[0]:
            if len(path) == 1:
                return box
            else:
                return _find_box_at_pathx(
                    T.cast(T.Iterable[BoxDict], box["data"]), path[1:]
                )
    raise ValueError(f"box at path {path} not found")


def _filter_trak_boxes(
    boxes: T.Iterable[BoxDict],
) -> T.Generator[BoxDict, None, None]:
    for box in boxes:
        if box["type"] == b"trak":
            yield box


def _is_video_trak(box: BoxDict) -> bool:
    hdlr = _find_box_at_pathx(box, [b"trak", b"mdia", b"hdlr"])
    return T.cast(T.Dict[str, T.Any], hdlr["data"])["handler_type"] == b"vide"


def _filter_moov_children_boxes(
    children: T.Iterable[BoxDict],
) -> T.Generator[BoxDict, None, None]:
    for box in children:
        if box["type"] == b"trak":
            if _is_video_trak(box):
                yield box
        elif box["type"] == b"mvhd":
            yield box


def _update_sbtl(trak: BoxDict, sample_offset: int) -> int:
    assert trak["type"] == b"trak"
    new_samples = []
    for sample in iterate_samples([trak]):
        new_samples.append(
            parser.RawSample(
                description_idx=sample.description_idx,
                offset=sample_offset,
                size=sample.size,
                timedelta=sample.timedelta,
                is_sync=sample.is_sync,
            )
        )
        sample_offset += sample.size
    stbl_box = _find_box_at_pathx(trak, [b"trak", b"mdia", b"minf", b"stbl"])
    descriptions, _ = parser.parse_raw_samples_from_stbl(
        io.BytesIO(T.cast(bytes, stbl_box["data"]))
    )
    stbl_children_boxes = builder.build_stbl_from_raw_samples(descriptions, new_samples)
    new_stbl_bytes = builder.FullBoxStruct32.BoxList.build(stbl_children_boxes)
    stbl_box["data"] = new_stbl_bytes

    return sample_offset


def _update_all_trak_tkhd(moov_chilren: T.Sequence[BoxDict]) -> None:
    # an integer that uniquely identifies this track over the entire life-time of this presentation.
    # Track IDs are never re-used and cannot be zero.
    track_id = 1

    # tracks with lower numbers are closer to the viewer.
    # 0 is the normal value, and -1 would be in front of track 0, and so on.
    layer = 0

    for box in _filter_trak_boxes(moov_chilren):
        tkhd = _find_box_at_pathx(box, [b"trak", b"tkhd"])
        d = T.cast(T.Dict[str, T.Any], tkhd["data"])
        d["track_id"] = track_id
        track_id += 1
        d["layer"] = layer
        layer += 1
    mvhd = _find_box_at_pathx(moov_chilren, [b"mvhd"])
    T.cast(T.Dict[str, T.Any], mvhd["data"])["next_track_ID"] = track_id


def _convert_points_to_raw_samples(
    points: T.Sequence[geo.Point], timescale: int
) -> T.Generator[parser.RawSample, None, None]:
    for idx, point in enumerate(points):
        camm_sample_data = camm_builder.build_camm_sample(point)

        if idx + 1 < len(points):
            timedelta = int((points[idx + 1].time - point.time) * timescale)
        else:
            timedelta = 0
        assert timedelta <= builder.UINT32_MAX

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


def _create_camm_trak(
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

    now = int(time.time())

    media_duration = sum(s.timedelta for s in raw_samples)

    # Media Header Box
    mdhd = {
        "type": b"mdhd",
        "data": {
            "creation_time": now,
            "modification_time": now,
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
            "creation_time": now,
            "modification_time": now,
            # will update later
            "track_ID": 0,
            # If the duration of this track cannot be determined then duration is set to all 1s (32-bit maxint).
            "duration": 0xFFFFFFFF,
            # will update later
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


def _build_moov_bytes(moov_children: T.Sequence[BoxDict]) -> bytes:
    return builder.QuickBoxStruct32.Box.build(
        {
            "type": b"moov",
            "data": moov_children,
        }
    )


def iterate_samples(
    moov_children: T.Iterable[BoxDict],
) -> T.Generator[parser.RawSample, None, None]:
    for box in moov_children:
        if box["type"] == b"trak":
            stbl_box = _find_box_at_pathx(box, [b"trak", b"mdia", b"minf", b"stbl"])
            _, raw_samples_iter = parser.parse_raw_samples_from_stbl(
                io.BytesIO(T.cast(bytes, stbl_box["data"]))
            )
            yield from raw_samples_iter


def _build_mdat_header_bytes(mdat_size: int) -> bytes:
    if parser.UINT32_MAX < mdat_size + 8:
        return builder.BoxHeader64.build(
            {
                "size": mdat_size + 16,
                "type": b"mdat",
            }
        )
    else:
        return builder.BoxHeader32.build(
            {
                "size": mdat_size + 8,
                "type": b"mdat",
            }
        )


class Reader:
    def read(self):
        raise NotImplementedError


@dataclass
class SampleReader(Reader):
    __slots__ = ("fp", "offset", "size")

    fp: T.BinaryIO
    offset: int
    size: int

    def read(self):
        self.fp.seek(self.offset)
        return self.fp.read(self.size)


@dataclass
class CAMMPointReader(Reader):
    __slots__ = ("point",)

    def __init__(self, point: geo.Point):
        self.point = point

    def read(self):
        return camm_builder.build_camm_sample(self.point)


def extract_points(fp: T.BinaryIO) -> T.Tuple[str, T.List[geo.Point]]:
    offset = fp.tell()
    points = camm_parser.extract_points(fp)
    if points:
        return "camm", points

    fp.seek(offset)
    points_with_fix = gpmf_parser.extract_points(fp)
    if points_with_fix:
        return "gopro", T.cast(T.List[geo.Point], points_with_fix)

    fp.seek(offset)
    points = blackvue_utils.extract_points(fp)
    if points:
        return "blackvue", points

    return "unknown", []


def transform_mp4(src_path: pathlib.Path, target_path: pathlib.Path):
    with open(src_path, "rb") as src_fp:
        # extract ftyp
        src_fp.seek(0)
        source_ftyp_box_data = parser.parse_data_firstx(src_fp, [b"ftyp"])
        source_ftyp_data = builder.QuickBoxStruct32.Box.build(
            {"type": b"ftyp", "data": source_ftyp_box_data}
        )

        # extract moov
        src_fp.seek(0)
        src_moov_data = parser.parse_data_firstx(src_fp, [b"moov"])
        moov_children = builder.QuickBoxStruct64.BoxList.parse(src_moov_data)

        # filter tracks in moov
        moov_children = list(_filter_moov_children_boxes(moov_children))

        # extract video samples
        source_samples = list(iterate_samples(moov_children))
        video_sample_readers = (
            SampleReader(src_fp, sample.offset, sample.size)
            for sample in source_samples
        )

        # append CAMM samples
        src_fp.seek(0)
        _, points = extract_points(src_fp)
        if not points:
            raise ValueError("no points found")

        media_timescale = 10000
        camm_samples = list(_convert_points_to_raw_samples(points, media_timescale))
        camm_trak = _create_camm_trak(camm_samples, media_timescale)
        moov_children.append(camm_trak)
        _update_all_trak_tkhd(moov_children)

        camm_sample_readers = (CAMMPointReader(point) for point in points)
        sample_readers: T.Iterator[Reader] = itertools.chain(
            video_sample_readers, camm_sample_readers
        )

        # moov_boxes should be immutable since here
        with open(target_path, "wb") as target_fp:
            target_fp.write(source_ftyp_data)
            target_fp.write(rewrite_moov(target_fp.tell(), moov_children))
            mdat_body_size = sum(
                sample.size for sample in iterate_samples(moov_children)
            )
            write_mdat(target_fp, mdat_body_size, sample_readers)


def rewrite_moov(moov_offset: int, moov_boxes: T.Sequence[BoxDict]) -> bytes:
    # build moov for calculating moov size
    sample_offset = 0
    for box in _filter_trak_boxes(moov_boxes):
        sample_offset = _update_sbtl(box, sample_offset)
    moov_data = _build_moov_bytes(moov_boxes)
    moov_data_size = len(moov_data)

    # mdat header size
    mdat_body_size = sum(sample.size for sample in iterate_samples(moov_boxes))
    mdat_header = _build_mdat_header_bytes(mdat_body_size)

    # build moov for real
    sample_offset = moov_offset + len(moov_data) + len(mdat_header)
    for box in _filter_trak_boxes(moov_boxes):
        sample_offset = _update_sbtl(box, sample_offset)
    moov_data = _build_moov_bytes(moov_boxes)
    assert len(moov_data) == moov_data_size, f"{len(moov_data)} != {moov_data_size}"

    return moov_data


def write_mdat(fp: T.BinaryIO, mdat_body_size: int, sample_readers: T.Iterable[Reader]):
    mdat_header = _build_mdat_header_bytes(mdat_body_size)
    fp.write(mdat_header)
    for reader in sample_readers:
        fp.write(reader.read())


def main():
    def _parse_args():
        parser = argparse.ArgumentParser()
        parser.add_argument("source_mp4_path", help="where to read the MP4")
        parser.add_argument(
            "target_mp4_path", help="where to write the transformed MP4"
        )
        return parser.parse_args()

    parsed_args = _parse_args()
    transform_mp4(
        pathlib.Path(parsed_args.source_mp4_path),
        pathlib.Path(parsed_args.target_mp4_path),
    )


if __name__ == "__main__":
    main()
