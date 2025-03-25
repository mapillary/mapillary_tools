from __future__ import annotations

import argparse
import io
import logging
import pathlib
import sys
import typing as T

from mapillary_tools import utils
from mapillary_tools.mp4 import (
    construct_mp4_parser as cparser,
    mp4_sample_parser as sample_parser,
    simple_mp4_parser as sparser,
)

LOG = logging.getLogger(__name__)

box_list_types = {
    b"dinf",
    b"edts",
    b"gmhd",
    b"mdia",
    b"minf",
    b"moof",
    b"moov",
    b"mvex",
    b"schi",
    b"stbl",
    b"traf",
    b"trak",
    b"udta",
}


def _validate_samples(path: pathlib.Path, filters: T.Container[bytes] | None = None):
    raw_samples: list[sample_parser.RawSample] = []

    parser = sample_parser.MovieBoxParser.parse_file(path)
    for track in parser.extract_tracks():
        for sample in track.extract_samples():
            if filters is None or sample.description["format"] in filters:
                raw_samples.append(sample.raw_sample)

    raw_samples.sort(key=lambda s: s.offset)
    if not raw_samples:
        return

    last_sample = None
    last_read = raw_samples[0].offset
    for raw_sample in raw_samples:
        if raw_sample.offset < last_read:
            LOG.warning(f"overlap found:\n{last_sample}\n{sample}")
        elif raw_sample.offset == last_read:
            pass
        else:
            LOG.warning(f"gap found:\n{last_sample}\n{sample}")
        last_read = raw_sample.offset + raw_sample.size
        last_sample = sample


def _parse_structs(fp: T.BinaryIO):
    for h, d, s in sparser.parse_boxes_recursive(fp, box_list_types=box_list_types):
        margin = "\t" * d
        if h.size32 == 0:
            header = f"{str(h.type)} {h.box_size} (open-ended):"
        elif h.size32 == 1:
            header = f"{str(h.type)} {h.box_size} (extended):"
        else:
            header = f"{str(h.type)} {h.box_size}:"
        if h.type in box_list_types:
            print(margin, header)
        else:
            if h.maxsize == -1:
                data = s.read(32)
            else:
                data = s.read(min(h.maxsize, 32))
            print(margin, header, data)


def _dump_box_data_at(fp: T.BinaryIO, box_type_path: list[bytes]):
    for h, s in sparser.parse_path(fp, box_type_path):
        max_chunk_size = 1024
        read = 0
        while read < h.maxsize or h.maxsize == -1:
            data = s.read(
                max_chunk_size
                if h.maxsize == -1
                else min((h.maxsize - read), max_chunk_size)
            )
            if not data:
                break
            sys.stdout.buffer.write(data)
            read += len(data)
        break


def _parse_samples(fp: T.BinaryIO, filters: T.Container[bytes] | None = None):
    parser = sample_parser.MovieBoxParser.parse_stream(fp)
    for track in parser.extract_tracks():
        box = track.extract_mdhd_boxdata()
        LOG.info(box)
        LOG.info(sample_parser.to_datetime(box["creation_time"]))
        LOG.info(box["duration"] / box["timescale"])

        for sample in track.extract_samples():
            if filters is None or sample.description["format"] in filters:
                print(sample)


def _dump_samples(fp: T.BinaryIO, filters: T.Container[bytes] | None = None):
    parser = sample_parser.MovieBoxParser.parse_stream(fp)
    for track in parser.extract_tracks():
        for sample in track.extract_samples():
            if filters is None or sample.description["format"] in filters:
                fp.seek(sample.raw_sample.offset, io.SEEK_SET)
                data = fp.read(sample.raw_sample.size)
                sys.stdout.buffer.write(data)


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--samples", action="store_true", default=False, help="show sample structs"
    )
    parser.add_argument(
        "--filter_samples",
        help="filter sample by types",
    )
    parser.add_argument(
        "--validate_samples",
        action="store_true",
        default=False,
        help="validate samples",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        default=False,
        help="dump as bytes or not",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        default=False,
        help="parse MP4 with the full parser or not, otherwise parse with the quick parser",
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        default=False,
        help="parse MP4 with the simple parser or not, otherwise parse with the quick parser",
    )
    parser.add_argument(
        "--box_path",
        required=False,
        help="show box data at path like this: moov/trak/minf",
    )
    parser.add_argument("path", nargs="+")
    return parser.parse_args()


def _process_path(parsed_args, path: pathlib.Path):
    if parsed_args.filter_samples is None:
        filter_samples = None
    else:
        filter_samples = parsed_args.filter_samples.encode("utf8").split(b",")

    if parsed_args.validate_samples:
        LOG.info(f"validating samples {path}")
        _validate_samples(path, filter_samples)

    if parsed_args.samples:
        if parsed_args.dump:
            with open(path, "rb") as fp:
                _dump_samples(fp, filter_samples)
        else:
            LOG.info(f"sampling {path}")
            with open(path, "rb") as fp:
                _parse_samples(fp, filter_samples)
    else:
        if parsed_args.box_path is None:
            box_path = None
        else:
            box_path = parsed_args.box_path.encode("utf8").split(b"/")

        if parsed_args.dump:
            LOG.info(f"dumping {path}")
            assert box_path is not None, "must specify --box_path"
            with open(path, "rb") as fp:
                _dump_box_data_at(fp, box_path)
        else:
            LOG.info(f"parsing {path}")
            with open(path, "rb") as fp:
                if parsed_args.simple:
                    if box_path is None:
                        _parse_structs(fp)
                    else:
                        data = sparser.parse_mp4_data_firstx(fp, box_path)
                        _parse_structs(io.BytesIO(data))
                elif parsed_args.full:
                    if box_path is None:
                        boxes = cparser.MP4ParserConstruct.BoxList.parse_stream(fp)
                    else:
                        data = sparser.parse_mp4_data_firstx(fp, box_path)
                        boxes = cparser.MP4ParserConstruct.BoxList.parse_stream(
                            io.BytesIO(data)
                        )
                    print(boxes)
                else:
                    if box_path is None:
                        boxes = (
                            cparser.MP4WithoutSTBLParserConstruct.BoxList.parse_stream(
                                fp
                            )
                        )
                    else:
                        data = sparser.parse_mp4_data_firstx(fp, box_path)
                        boxes = (
                            cparser.MP4WithoutSTBLParserConstruct.BoxList.parse_stream(
                                io.BytesIO(data)
                            )
                        )
                    print(boxes)


def main():
    parsed_args = _parse_args()

    for p in utils.find_videos([pathlib.Path(p) for p in parsed_args.path]):
        _process_path(parsed_args, p)


if __name__ == "__main__":
    main()
