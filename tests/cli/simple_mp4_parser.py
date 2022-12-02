import argparse
import io
import logging
import pathlib
import sys
import typing as T

from mapillary_tools import utils
from mapillary_tools.geotag import (
    construct_mp4_parser as cparser,
    mp4_sample_parser as sample_parser,
    simple_mp4_parser as parser,
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


def _validate_samples(
    path: pathlib.Path, filters: T.Optional[T.Container[bytes]] = None
):
    samples: T.List[sample_parser.RawSample] = []

    with open(path, "rb") as fp:
        for h, s in parser.parse_path(
            fp, [b"moov", b"trak", b"mdia", b"minf", b"stbl"]
        ):
            (
                descriptions,
                raw_samples,
            ) = sample_parser.parse_raw_samples_from_stbl(s, maxsize=h.maxsize)
            samples.extend(
                sample
                for sample in raw_samples
                if filters is None
                or descriptions[sample.description_idx]["format"] in filters
            )
    samples.sort(key=lambda s: s.offset)
    if not samples:
        return
    last_sample = None
    last_read = samples[0].offset
    for sample in samples:
        if sample.offset < last_read:
            LOG.warning(f"overlap found:\n{last_sample}\n{sample}")
        elif sample.offset == last_read:
            pass
        else:
            LOG.warning(f"gap found:\n{last_sample}\n{sample}")
        last_read = sample.offset + sample.size
        last_sample = sample


def _parse_structs(fp: T.BinaryIO):
    for h, d, s in parser.parse_boxes_recursive(fp, box_list_types=box_list_types):
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


def _dump_box_data_at(fp: T.BinaryIO, box_type_path: T.List[bytes]):
    for h, s in parser.parse_path(fp, box_type_path):
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


def _parse_samples(fp: T.BinaryIO, filters: T.Optional[T.Container[bytes]] = None):
    for h, s in parser.parse_path(fp, [b"moov", b"trak"]):
        offset = s.tell()
        for h1, s1 in parser.parse_path(s, [b"mdia", b"mdhd"], maxsize=h.maxsize):
            box = cparser.MediaHeaderBox.parse(s1.read(h.maxsize))
            LOG.info(box)
            LOG.info(sample_parser.to_datetime(box.creation_time))
            LOG.info(box.duration / box.timescale)
        s.seek(offset, io.SEEK_SET)
        for sample in sample_parser.parse_samples_from_trak(s, maxsize=h.maxsize):
            if filters is None or sample.description["format"] in filters:
                print(sample)


def _dump_samples(fp: T.BinaryIO, filters: T.Optional[T.Container[bytes]] = None):
    for h, s in parser.parse_path(fp, [b"moov", b"trak"]):
        for sample in sample_parser.parse_samples_from_trak(s, maxsize=h.maxsize):
            if filters is None or sample.description["format"] in filters:
                fp.seek(sample.offset, io.SEEK_SET)
                data = fp.read(sample.size)
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
                        data = parser.parse_mp4_data_firstx(fp, box_path)
                        _parse_structs(io.BytesIO(data))
                elif parsed_args.full:
                    if box_path is None:
                        boxes = cparser.MP4ParserConstruct.BoxList.parse_stream(fp)
                    else:
                        data = parser.parse_mp4_data_firstx(fp, box_path)
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
                        data = parser.parse_mp4_data_firstx(fp, box_path)
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
