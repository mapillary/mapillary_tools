import os
import argparse
import io

from mapillary_tools import utils
from mapillary_tools.geotag import simple_mp4_parser

if __name__ == "__main__":

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

    def _validate_samples(path: str):
        samples = []
        with open(path, "rb") as fp:
            for h, s in simple_mp4_parser.parse_path(
                fp, [b"moov", b"trak", b"mdia", b"minf", b"stbl"]
            ):
                samples.extend(
                    list(
                        simple_mp4_parser.parse_samples_from_stbl(s, maxsize=h.maxsize)
                    )
                )
        samples.sort(key=lambda s: s.offset)
        if not samples:
            return
        last_sample = None
        last_read = samples[0].offset
        for sample in samples:
            if sample.offset < last_read:
                print(f"overlap found:\n{last_sample}\n{sample}")
            elif sample.offset == last_read:
                pass
            else:
                print(f"gap found:\n{last_sample}\n{sample}")
            last_read = sample.offset + sample.size
            last_sample = sample

    def _parse_file(path: str):
        with open(path, "rb") as fp:
            for h, d, s in simple_mp4_parser.parse_boxes_recursive(
                fp, box_list_types=box_list_types
            ):
                margin = "\t" * d
                try:
                    utfh = h.type.decode("utf8")
                except UnicodeDecodeError:
                    utfh = str(h)
                header = f"{utfh} {h.box_size}:"
                if h.type in box_list_types:
                    print(margin, header)
                else:
                    print(margin, header, s.read(min(h.maxsize, 32)))

    def _parse_samples(path: str):
        with open(path, "rb") as fp:
            for h, s in simple_mp4_parser.parse_path(fp, [b"moov", b"trak"]):
                offset = s.tell()
                for h1, s1 in simple_mp4_parser.parse_path(
                    s, [b"mdia", b"mdhd"], maxsize=h.maxsize
                ):
                    box = simple_mp4_parser.MediaHeaderBox.parse(s1.read(h.maxsize))
                    print(box)
                    print(simple_mp4_parser.to_datetime(box.creation_time))
                    print(box.duration / box.timescale)
                s.seek(offset, io.SEEK_SET)
                for sample in simple_mp4_parser.parse_samples_from_trak(
                    s, maxsize=h.maxsize
                ):
                    print(sample)

    def _parse_args():
        parser = argparse.ArgumentParser()
        parser.add_argument("--samples", action="store_true", default=False)
        parser.add_argument("--validate", action="store_true", default=False)
        parser.add_argument("--header", action="store_true", default=False)
        parser.add_argument("path", nargs="+")
        return parser.parse_args()

    parsed = _parse_args()

    def _process_path(path: str):
        if parsed.validate:
            print(f"validating {path}")
            _validate_samples(path)

        if parsed.samples:
            print(f"sampling {path}")
            _parse_samples(path)
        else:
            print(f"parsing {path}")
            _parse_file(path)

    for path in parsed.path:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                _process_path(p)
        else:
            _process_path(path)
