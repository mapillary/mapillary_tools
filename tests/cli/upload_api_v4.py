import argparse
import sys
import hashlib
import os
import typing as T
import logging

import requests
import tqdm
from mapillary_tools import upload

from mapillary_tools.upload_api_v4 import (
    DEFAULT_CHUNK_SIZE,
    UploadService,
    wrap_http_exception,
)


LOG = logging.getLogger("mapillary_tools")


def configure_logger(logger: logging.Logger, stream=None) -> None:
    formatter = logging.Formatter("%(asctime)s - %(levelname)-7s - %(message)s")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def _file_stats(fp: T.IO[bytes]):
    md5 = hashlib.md5()
    while True:
        buf = fp.read(DEFAULT_CHUNK_SIZE)
        if not buf:
            break
        md5.update(buf)
    fp.seek(0, os.SEEK_END)
    return md5.hexdigest(), fp.tell()


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verbose",
        help="show verbose",
        action="store_true",
        default=False,
        required=False,
    )
    parser.add_argument("--user_name")
    parser.add_argument("filename")
    parser.add_argument("session_key", nargs="?")
    return parser.parse_args()


def main():
    parsed = _parse_args()

    log_level = logging.DEBUG if parsed.verbose else logging.INFO
    configure_logger(LOG, sys.stderr)
    LOG.setLevel(log_level)

    with open(parsed.filename, "rb") as fp:
        md5sum, entity_size = _file_stats(fp)

    user_items = upload.fetch_user_items(parsed.user_name)

    session_key = (
        parsed.session_key
        if parsed.session_key is not None
        else f"mly_tools_test_{md5sum}"
    )
    user_access_token = user_items.get("user_upload_token", "")
    service = UploadService(user_access_token, session_key, entity_size)

    LOG.info(f"Session key: {session_key}")
    LOG.info(f"Entity size: {entity_size}")
    LOG.info(f"Initial offset: {service.fetch_offset()}")

    with open(parsed.filename, "rb") as fp:
        with tqdm.tqdm(
            total=entity_size,
            initial=service.fetch_offset(),
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        ) as pbar:
            service.callbacks.append(lambda chunk, resp: pbar.update(len(chunk)))
            try:
                file_handle = service.upload(fp)
            except requests.HTTPError as ex:
                raise wrap_http_exception(ex)

    LOG.info(file_handle)


if __name__ == "__main__":
    main()
