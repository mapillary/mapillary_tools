from __future__ import annotations

import contextlib
import dbm
import json
import logging
import string
import threading
import time
import typing as T
from pathlib import Path

# dbm modules are dynamically imported, so here we explicitly import dbm.sqlite3 to make sure pyinstaller include it
# Otherwise you will see: ImportError: no dbm clone found; tried ['dbm.sqlite3', 'dbm.gnu', 'dbm.ndbm', 'dbm.dumb']
try:
    import dbm.sqlite3  # type: ignore
except ImportError:
    pass


from . import constants, types
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
    _lock: contextlib.nullcontext | threading.Lock

    def __init__(self, file: str):
        # SQLite3 backend supports concurrent access without a lock
        if dbm.whichdb(file) == "dbm.sqlite3":
            self._lock = contextlib.nullcontext()
        else:
            self._lock = threading.Lock()
        self._file = file

    def get(self, key: str) -> str | None:
        s = time.perf_counter()

        with self._lock:
            with dbm.open(self._file, flag="c") as db:
                value: bytes | None = db.get(key)

        if value is None:
            return None

        payload = self._decode(value)

        if self._is_expired(payload):
            return None

        file_handle = payload.get("file_handle")

        LOG.debug(
            f"Found file handle for {key} in cache ({(time.perf_counter() - s) * 1000:.0f} ms)"
        )

        return T.cast(str, file_handle)

    def set(self, key: str, file_handle: str, expires_in: int = 3600 * 24 * 2) -> None:
        s = time.perf_counter()

        payload = {
            "expires_at": time.time() + expires_in,
            "file_handle": file_handle,
        }

        value: bytes = json.dumps(payload).encode("utf-8")

        with self._lock:
            with dbm.open(self._file, flag="c") as db:
                db[key] = value

        LOG.debug(
            f"Cached file handle for {key} ({(time.perf_counter() - s) * 1000:.0f} ms)"
        )

    def clear_expired(self) -> list[str]:
        s = time.perf_counter()

        expired_keys: list[str] = []

        with self._lock:
            with dbm.open(self._file, flag="c") as db:
                if hasattr(db, "items"):
                    items: T.Iterable[tuple[str | bytes, bytes]] = db.items()
                else:
                    items = ((key, db[key]) for key in db.keys())

                for key, value in items:
                    payload = self._decode(value)
                    if self._is_expired(payload):
                        del db[key]
                        expired_keys.append(T.cast(str, key))

        if expired_keys:
            LOG.debug(
                f"Cleared {len(expired_keys)} expired entries from the cache ({(time.perf_counter() - s) * 1000:.0f} ms)"
            )

        return expired_keys

    def keys(self):
        with self._lock:
            with dbm.open(self._file, flag="c") as db:
                return db.keys()

    def _is_expired(self, payload: JSONDict) -> bool:
        expires_at = payload.get("expires_at")
        if isinstance(expires_at, (int, float)):
            return expires_at is None or expires_at <= time.time()
        return False

    def _decode(self, value: bytes) -> JSONDict:
        try:
            payload = json.loads(value.decode("utf-8"))
        except json.JSONDecodeError as ex:
            LOG.warning(f"Failed to decode cache value: {ex}")
            return {}

        if not isinstance(payload, dict):
            LOG.warning(f"Invalid cache value format: {payload}")
            return {}

        return payload
