import argparse
import io
import logging
import sys
import typing as T

import requests
import tqdm
from mapillary_tools import upload

from mapillary_tools.upload_api_v4 import DEFAULT_CHUNK_SIZE, UploadService


LOG = logging.getLogger("mapillary_tools")


def wrap_http_exception(ex: requests.HTTPError):
    resp = ex.response
    lines = [
        f"{ex.request.method} {resp.url}",
        f"> HTTP Status: {ex.response.status_code}",
        f"{resp.content}",
    ]
    return Exception("\n".join(lines))


def configure_logger(logger: logging.Logger, stream=None) -> None:
    formatter = logging.Formatter("%(asctime)s - %(levelname)-7s - %(message)s")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def _file_stats(fp: T.IO[bytes]) -> int:
    fp.seek(0, io.SEEK_END)
    return fp.tell()


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
    parser.add_argument(
        "--chunk_size",
        type=float,
        default=DEFAULT_CHUNK_SIZE / (1024 * 1024),
        help="chunk size in megabytes",
    )
    parser.add_argument("filename")
    parser.add_argument("session_key")
    return parser.parse_args()


def main():
    parsed = _parse_args()

    log_level = logging.DEBUG if parsed.verbose else logging.INFO
    configure_logger(LOG, sys.stderr)
    LOG.setLevel(log_level)

    with open(parsed.filename, "rb") as fp:
        entity_size = _file_stats(fp)

    user_items = upload.fetch_user_items(parsed.user_name)

    session_key = parsed.session_key
    user_access_token = user_items.get("user_upload_token", "")
    service = UploadService(
        user_access_token,
        session_key,
        entity_size,
        chunk_size=int(parsed.chunk_size * 1024 * 1024)
        if parsed.chunk_size is not None
        else DEFAULT_CHUNK_SIZE,
    )
    initial_offset = service.fetch_offset()

    LOG.info(f"Session key: %s", session_key)
    LOG.info(f"Entity size: %d", entity_size)
    LOG.info(f"Initial offset: %s", initial_offset)
    LOG.info(f"Chunk size: %s MB", service.chunk_size / (1024 * 1024))

    with open(parsed.filename, "rb") as fp:
        with tqdm.tqdm(
            total=entity_size,
            initial=initial_offset,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        ) as pbar:
            service.callbacks.append(lambda chunk, resp: pbar.update(len(chunk)))
            try:
                file_handle = service.upload(fp, initial_offset)
            except requests.HTTPError as ex:
                raise wrap_http_exception(ex)

    LOG.info(file_handle)


if __name__ == "__main__":
    main()
