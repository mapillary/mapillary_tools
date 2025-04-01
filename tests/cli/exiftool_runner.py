from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mapillary_tools import exiftool_runner, utils


LOG = logging.getLogger("mapillary_tools")


def configure_logger(logger: logging.Logger, stream=None) -> None:
    formatter = logging.Formatter("%(asctime)s - %(levelname)-7s - %(message)s")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="+", help="Paths to files or directories")
    return parser.parse_args()


def main():
    configure_logger(LOG, sys.stdout)
    LOG.setLevel(logging.INFO)

    parsed = parse_args()

    video_paths = utils.find_videos([Path(p) for p in parsed.path])
    image_paths = utils.find_images([Path(p) for p in parsed.path])

    LOG.info(
        "Found %d video files and %d image files", len(video_paths), len(image_paths)
    )

    runner = exiftool_runner.ExiftoolRunner("exiftool")
    xml = runner.extract_xml(image_paths + video_paths)

    print(xml)


if __name__ == "__main__":
    main()
