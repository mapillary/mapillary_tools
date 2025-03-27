import argparse
import io
import logging
import sys
import typing as T

import requests
import tqdm
from mapillary_tools import api_v4, authenticate

from mapillary_tools.upload_api_v4 import FakeUploadService, UploadService


LOG = logging.getLogger("mapillary_tools")


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
        default=2,
        help="chunk size in megabytes",
    )
    parser.add_argument("--dry_run", action="store_true", default=False)
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

    user_items = authenticate.fetch_user_items(parsed.user_name)

    session_key = parsed.session_key
    chunk_size = int(parsed.chunk_size * 1024 * 1024)
    user_access_token = user_items.get("user_upload_token", "")

    if parsed.dry_run:
        service = FakeUploadService(user_access_token, session_key)
    else:
        service = UploadService(user_access_token, session_key)

    try:
        initial_offset = service.fetch_offset()
    except requests.HTTPError as ex:
        raise RuntimeError(api_v4.readable_http_error(ex))

    LOG.info("Session key: %s", session_key)
    LOG.info("Initial offset: %s", initial_offset)
    LOG.info("Entity size: %d", entity_size)
    LOG.info("Chunk size: %s MB", chunk_size / (1024 * 1024))

    def _update_pbar(chunks, pbar):
        for chunk in chunks:
            yield chunk
            pbar.update(len(chunk))

    with open(parsed.filename, "rb") as fp:
        fp.seek(initial_offset, io.SEEK_SET)

        shifted_chunks = service.chunkize_byte_stream(fp, chunk_size)

        with tqdm.tqdm(
            total=entity_size,
            initial=initial_offset,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        ) as pbar:
            try:
                file_handle = service.upload_shifted_chunks(
                    _update_pbar(shifted_chunks, pbar), initial_offset
                )
            except requests.HTTPError as ex:
                raise RuntimeError(api_v4.readable_http_error(ex))
            except KeyboardInterrupt:
                file_handle = None
                LOG.warning("Upload interrupted")

    try:
        final_offset = service.fetch_offset()
    except requests.HTTPError as ex:
        raise RuntimeError(api_v4.readable_http_error(ex))

    LOG.info("Final offset: %s", final_offset)
    LOG.info("Entity size: %d", entity_size)
    LOG.info("File handle: %s", file_handle)


if __name__ == "__main__":
    main()
