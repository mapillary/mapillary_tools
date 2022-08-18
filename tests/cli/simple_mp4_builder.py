import argparse
import io
import pathlib
import typing as T
from dataclasses import dataclass

import mapillary_tools.geotag.simple_mp4_builder as builder
import mapillary_tools.geotag.simple_mp4_parser as parser
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
    return hdlr["data"]["handler_type"] == b"vide"


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


def transform_mp4(src_path: pathlib.Path, target_path: pathlib.Path):
    with open(src_path, "rb") as src_fp:
        h, s = parser.parse_path_firstx(src_fp, [b"ftyp"])
        source_ftyp_data = builder.QuickBoxStruct32.Box.build(
            {"type": b"ftyp", "data": s.read(h.maxsize)}
        )

        h, s = parser.parse_path_firstx(src_fp, [b"moov"])
        moov_boxes = builder.QuickBoxStruct64.BoxList.parse(s.read(h.maxsize))

        moov_boxes = list(_filter_moov_children_boxes(moov_boxes))

        # moov_boxes should be immutable since here
        source_samples = list(iterate_samples(moov_boxes))
        sample_readers = (
            SampleReader(src_fp, sample.offset, sample.size)
            for sample in source_samples
        )

        with open(target_path, "wb") as target_fp:
            target_fp.write(source_ftyp_data)
            target_fp.write(rewrite_moov(target_fp.tell(), moov_boxes))
            mdat_body_size = sum(sample.size for sample in iterate_samples(moov_boxes))
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


def write_mdat(
    fp: T.BinaryIO, mdat_body_size: int, sample_readers: T.Iterable[SampleReader]
):
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
