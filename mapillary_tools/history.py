# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sqlite3
import threading
import time
import typing as T
from functools import wraps
from pathlib import Path

from . import constants, fingerprint, store

JSONDict = T.Dict[str, T.Union[str, int, float, None]]

LOG = logging.getLogger(__name__)


# Uploaded files are recorded by fingerprint (see fingerprint.py), one record
# per uploaded image sequence, video or zip file, in this folder of the upload
# history. Records written by earlier versions, by checksum, are not read
UPLOADED_FILES_DIR = "fingerprints_v1"

# Later upload times are not taken: 3000-01-01, which every platform shows as
# a local time
_MAX_UPLOADED_AT = 32503680000


@dataclasses.dataclass(frozen=True)
class UploadedFile:
    filename: Path
    filesize: int
    fingerprint: str


@dataclasses.dataclass
class UploadedFiles:
    """
    The files recorded in the upload history: their sizes, and when each
    fingerprint was uploaded (None if not known)
    """

    sizes: set[int] = dataclasses.field(default_factory=set)
    uploaded_at: dict[str, float | None] = dataclasses.field(default_factory=dict)

    def find(
        self, path: Path, fingerprints: dict[Path, str] | None = None
    ) -> str | None:
        """
        Return the fingerprint of the file if it was uploaded, or None. The
        file is read only when an uploaded file had the same size. Computed
        fingerprints are kept in the fingerprints given, by path.
        """
        if os.path.getsize(path) not in self.sizes:
            return None
        file_fingerprint = None if fingerprints is None else fingerprints.get(path)
        if file_fingerprint is None:
            file_fingerprint = fingerprint.fingerprint_file(path)
            if fingerprints is not None:
                fingerprints[path] = file_fingerprint
        if file_fingerprint not in self.uploaded_at:
            return None
        return file_fingerprint

    def add(self, files: T.Iterable[UploadedFile], uploaded_at: float | None) -> None:
        for file in files:
            self.sizes.add(file.filesize)
            previous = self.uploaded_at.get(file.fingerprint)
            if previous is None or (uploaded_at is not None and previous < uploaded_at):
                self.uploaded_at[file.fingerprint] = uploaded_at


def _uploaded_files_dir() -> Path:
    return Path(constants.MAPILLARY_UPLOAD_HISTORY_PATH).joinpath(UPLOADED_FILES_DIR)


def is_unfinished_upload(record: T.Any) -> bool:
    """
    Tell whether an upload history record is of an upload that Mapillary did
    not finish, so nothing was uploaded: its summary has the cluster ID null.
    upload wrote such records when finish_upload answered without a cluster
    ID, as for an organization that the account is not a member of. Only an
    explicit null counts: records written before 0.14.0 have no cluster ID.
    """
    if not isinstance(record, dict):
        return False
    summary = record.get("summary")
    return (
        isinstance(summary, dict)
        and "cluster_id" in summary
        and summary["cluster_id"] is None
    )


def read_uploaded_files() -> UploadedFiles | None:
    """
    Read the files recorded in the upload history, in one pass over its
    records, or return None if there is no upload history
    """
    if not constants.MAPILLARY_UPLOAD_HISTORY_PATH:
        return None

    uploaded = UploadedFiles()
    root = _uploaded_files_dir()
    if not root.is_dir():
        return uploaded

    try:
        for path in root.glob("*/*.json"):
            try:
                with path.open("r", encoding="utf-8") as fp:
                    record = json.load(fp)
            except (OSError, UnicodeError, json.JSONDecodeError) as ex:
                LOG.warning("Failed to read upload history %s: %s", path, ex)
                continue
            if is_unfinished_upload(record):
                LOG.info(
                    "Not taken as uploaded: the upload in the history record %s was not finished",
                    path,
                )
                continue
            if not _add_uploaded_files_record(uploaded, record):
                LOG.warning("Invalid upload history record %s", path)
    except OSError as ex:
        LOG.warning("Failed to scan upload history %s: %s", root, ex)

    return uploaded


def _add_uploaded_files_record(uploaded: UploadedFiles, record: T.Any) -> bool:
    if not isinstance(record, dict) or not isinstance(record.get("files"), list):
        return False

    summary = record.get("summary")
    uploaded_at = summary.get("upload_end_time") if isinstance(summary, dict) else None
    if (
        isinstance(uploaded_at, bool)
        or not isinstance(uploaded_at, (int, float))
        # Also not NaN
        or not 0 <= uploaded_at <= _MAX_UPLOADED_AT
    ):
        uploaded_at = None

    files: list[UploadedFile] = []
    for entry in record["files"]:
        if not isinstance(entry, dict):
            return False
        filesize = entry.get("filesize")
        file_fingerprint = entry.get("fingerprint")
        if (
            isinstance(filesize, bool)
            or not isinstance(filesize, int)
            or filesize < 0
            or not fingerprint.is_fingerprint(file_fingerprint)
        ):
            return False
        files.append(
            UploadedFile(
                Path(str(entry.get("filename"))),
                filesize,
                T.cast(str, file_fingerprint),
            )
        )

    uploaded.add(files, uploaded_at)
    return True


def write_uploaded_files(
    files: T.Sequence[UploadedFile], params: JSONDict, summary: JSONDict
) -> None:
    """Record the files of an uploaded image sequence, video or zip file"""
    if not constants.MAPILLARY_UPLOAD_HISTORY_PATH or not files:
        return
    key = fingerprint.combine_fingerprints(file.fingerprint for file in files)
    path = _uploaded_files_dir().joinpath(key[:2]).joinpath(f"{key[2:]}.json")
    LOG.debug("Writing upload history: %s", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "params": params,
        "summary": summary,
        "files": [
            {
                "filename": os.path.abspath(file.filename),
                "filesize": file.filesize,
                "fingerprint": file.fingerprint,
            }
            for file in files
        ],
    }
    with open(path, "w") as fp:
        fp.write(json.dumps(record))


def _retry_on_database_lock_error(fn):
    """
    Decorator to retry a function if it raises a sqlite3.OperationalError with
    "database is locked" in the message.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        while True:
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as ex:
                if "database is locked" in str(ex).lower():
                    LOG.warning(f"{str(ex)}")
                    LOG.info("Retrying in 1 second...")
                    time.sleep(1)
                else:
                    raise ex

    return wrapper


class PersistentCache:
    _lock: threading.Lock

    def __init__(self, file: str):
        self._file = file
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        if not self._db_existed():
            return None

        s = time.perf_counter()

        try:
            db_ctx = store.KeyValueStore(self._file, flag="r")
        except sqlite3.DatabaseError as ex:
            LOG.warning(f"Failed to open cache database: {ex}")
            return None

        with db_ctx as db:
            try:
                raw_payload: bytes | None = db.get(key)  # data retrieved from db[key]
            except Exception as ex:
                if self._table_not_found(ex):
                    return None
                if isinstance(ex, sqlite3.DatabaseError):
                    LOG.warning(f"Cache read error for {key}: {ex}")
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

    @_retry_on_database_lock_error
    def set(self, key: str, value: str, expires_in: int = 3600 * 24 * 2) -> None:
        s = time.perf_counter()

        data = {
            "expires_at": time.time() + expires_in,
            "value": value,
        }

        payload: bytes = json.dumps(data).encode("utf-8")

        with self._lock:
            with store.KeyValueStore(self._file, flag="c") as db:
                db[key] = payload

        LOG.debug(
            f"Cached file handle for {key} ({(time.perf_counter() - s) * 1000:.0f} ms)"
        )

    def get_many(self, keys: T.Iterable[str]) -> dict[str, str]:
        """
        Get the values of the keys that are cached and not expired, with one
        database connection.
        """
        if not self._db_existed():
            return {}

        try:
            db_ctx = store.KeyValueStore(self._file, flag="r")
        except sqlite3.DatabaseError as ex:
            LOG.warning(f"Failed to open cache database: {ex}")
            return {}

        values: dict[str, str] = {}

        with db_ctx as db:
            try:
                for key in keys:
                    raw_payload: bytes | None = db.get(key)
                    if raw_payload is None:
                        continue
                    data = self._decode(raw_payload)
                    value = data.get("value")
                    if not self._is_expired(data) and isinstance(value, str):
                        values[key] = value
            except Exception as ex:
                if self._table_not_found(ex):
                    return {}
                if isinstance(ex, sqlite3.DatabaseError):
                    LOG.warning(f"Cache read error: {ex}")
                    return {}
                raise ex

        return values

    @_retry_on_database_lock_error
    def set_many(self, items: T.Mapping[str, str], expires_in: int) -> None:
        """
        Set the values in one transaction, so the database is synced to disk
        once, not once per value.
        """
        expires_at = time.time() + expires_in

        payloads = [
            (
                key,
                json.dumps({"expires_at": expires_at, "value": value}).encode("utf-8"),
            )
            for key, value in items.items()
        ]

        with self._lock:
            with store.KeyValueStore(self._file, flag="c") as db:
                db.set_many(payloads)

    @_retry_on_database_lock_error
    def clear_expired(self) -> list[str]:
        s = time.perf_counter()

        with self._lock:
            with store.KeyValueStore(self._file, flag="c") as db:
                expired_keys = T.cast(
                    list[str],
                    db.delete_matching(
                        lambda raw_payload: self._is_expired(self._decode(raw_payload))
                    ),
                )

        LOG.debug(
            f"Cleared {len(expired_keys)} expired entries from the cache ({(time.perf_counter() - s) * 1000:.0f} ms)"
        )

        return expired_keys

    def keys(self) -> list[str]:
        if not self._db_existed():
            return []

        try:
            with store.KeyValueStore(self._file, flag="r") as db:
                return [key.decode("utf-8") for key in db.keys()]
        except Exception as ex:
            if self._table_not_found(ex):
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
            LOG.warning(f"Invalid cache value format: {raw_payload!r}")
            return {}

        return data

    def _db_existed(self) -> bool:
        return os.path.exists(self._file)

    def _table_not_found(self, ex: Exception) -> bool:
        if isinstance(ex, sqlite3.OperationalError):
            if "no such table" in str(ex):
                return True
        return False
