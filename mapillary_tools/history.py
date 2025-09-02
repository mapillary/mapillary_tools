from __future__ import annotations

import json
import logging
import os

import sqlite3
import string
import threading
import time
import typing as T
from pathlib import Path

from . import constants, store, types
from .serializer.description import DescriptionJSONSerializer

JSONDict = T.Dict[str, T.Union[str, int, float, None]]

LOG = logging.getLogger(__name__)


def _validate_hexdigits(md5sum: str):
    try:
        assert set(md5sum).issubset(string.hexdigits)
        assert 4 <= len(md5sum)
        _ = int(md5sum, 16)
    except Exception:
        raise ValueError(f"Invalid md5sum {md5sum}")


def history_desc_path(md5sum: str) -> Path:
    _validate_hexdigits(md5sum)
    subfolder = md5sum[:2]
    assert subfolder, f"Invalid md5sum {md5sum}"
    basename = md5sum[2:]
    assert basename, f"Invalid md5sum {md5sum}"
    return (
        Path(constants.MAPILLARY_UPLOAD_HISTORY_PATH)
        .joinpath(subfolder)
        .joinpath(f"{basename}.json")
    )


def read_history_record(md5sum: str) -> None | T.Dict[str, T.Any]:
    if not constants.MAPILLARY_UPLOAD_HISTORY_PATH:
        return None

    path = history_desc_path(md5sum)

    if not path.is_file():
        return None

    with path.open("r") as fp:
        try:
            return json.load(fp)
        except json.JSONDecodeError as ex:
            LOG.error(f"Failed to read upload history {path}: {ex}")
            return None


def write_history(
    md5sum: str,
    params: JSONDict,
    summary: JSONDict,
    metadatas: T.Sequence[types.Metadata] | None = None,
) -> None:
    if not constants.MAPILLARY_UPLOAD_HISTORY_PATH:
        return
    path = history_desc_path(md5sum)
    LOG.debug("Writing upload history: %s", path)
    path.resolve().parent.mkdir(parents=True, exist_ok=True)
    history: dict[str, T.Any] = {"params": params, "summary": summary}
    if metadatas is not None:
        history["descs"] = [
            DescriptionJSONSerializer.as_desc(metadata) for metadata in metadatas
        ]
    with open(path, "w") as fp:
        fp.write(json.dumps(history))


class PersistentCache:
    _lock: threading.Lock

    def __init__(self, file: str):
        self._file = file
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        if not self._does_db_exist():
            return None

        s = time.perf_counter()

        with store.KeyValueStore(self._file, flag="r") as db:
            try:
                raw_payload: bytes | None = db.get(key)  # data retrieved from db[key]
            except Exception as ex:
                if self._does_table_exist(ex):
                    return None
                raise ex

        if raw_payload is None:
            return None

        data: JSONDict = self._decode(raw_payload)  # JSON dict decoded from db[key]

        if self._is_expired(data):
            return None

        cached_value = data.get("value")  # value in the JSON dict decoded from db[key]

        LOG.debug(
            f"Found file handle for {key} in cache ({(time.perf_counter() - s) * 1000:.0f} ms)"
        )

        return T.cast(str, cached_value)

    def set(self, key: str, value: str, expires_in: int = 3600 * 24 * 2) -> None:
        s = time.perf_counter()

        data = {
            "expires_at": time.time() + expires_in,
            "value": value,
        }

        payload: bytes = json.dumps(data).encode("utf-8")

        while True:
            try:
                with self._lock:
                    with store.KeyValueStore(self._file, flag="c") as db:
                        # Assume db exists
                        db[key] = payload
            except sqlite3.OperationalError as ex:
                if "database is locked" in str(ex).lower():
                    LOG.warning(
                        f"{str(ex)}: {self._file} (are you running multiple instances?)"
                    )
                    LOG.info("Retrying in 1 second...")
                    time.sleep(1)
                    continue
                else:
                    raise ex
            else:
                break

        LOG.debug(
            f"Cached file handle for {key} ({(time.perf_counter() - s) * 1000:.0f} ms)"
        )

    def clear_expired(self) -> list[str]:
        expired_keys: list[str] = []

        s = time.perf_counter()

        with self._lock:
            with store.KeyValueStore(self._file, flag="c") as db:
                # Assume db and table exist here
                for key, raw_payload in db.items():
                    data = self._decode(raw_payload)
                    if self._is_expired(data):
                        del db[key]
                        expired_keys.append(T.cast(str, key))

        LOG.debug(
            f"Cleared {len(expired_keys)} expired entries from the cache ({(time.perf_counter() - s) * 1000:.0f} ms)"
        )

        return expired_keys

    def keys(self) -> list[str]:
        if not self._does_db_exist():
            return []

        try:
            with store.KeyValueStore(self._file, flag="r") as db:
                return [key.decode("utf-8") for key in db.keys()]
        except Exception as ex:
            if self._does_table_exist(ex):
                return []
            raise ex

    def _is_expired(self, data: JSONDict) -> bool:
        expires_at = data.get("expires_at")
        if isinstance(expires_at, (int, float)):
            return expires_at is None or expires_at <= time.time()
        return False

    def _decode(self, raw_payload: bytes) -> JSONDict:
        try:
            data = json.loads(raw_payload.decode("utf-8"))
        except json.JSONDecodeError as ex:
            LOG.warning(f"Failed to decode cache value: {ex}")
            return {}

        if not isinstance(data, dict):
            LOG.warning(f"Invalid cache value format: {raw_payload}")
            return {}

        return data

    def _does_db_exist(self) -> bool:
        return os.path.exists(self._file)

    def _does_table_exist(self, ex: Exception) -> bool:
        if isinstance(ex, sqlite3.OperationalError):
            if "no such table" in str(ex):
                return True
        return False
