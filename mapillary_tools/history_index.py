# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
An index of the upload history by file size and fingerprint, so that looking
files up neither reads every record nor holds them all in memory.

The records stay the source of truth. The index is a SQLite file next to them,
brought up to date every time it is opened: only the records added, changed or
deleted since are read. A corrupt index is rebuilt from the records. When the
index can't be used, every record is read, as without the index.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import typing as T
from pathlib import Path

from . import constants, fingerprint, history

LOG = logging.getLogger(__name__)

# Change it with the tables. The version is in the file name, so that versions
# of mapillary_tools with different tables, like a Desktop Uploader and a
# command line install, each keep their own index instead of rebuilding it
SCHEMA_VERSION = 1
INDEX_FILENAME = f"index_v{SCHEMA_VERSION}.sqlite3"

# How long to wait for another mapillary_tools process that updates the index
LOCK_TIMEOUT_SECONDS = 30.0
# How long a lookup waits before every record is read instead
LOOKUP_TIMEOUT_SECONDS = 2.0

# One row per record (its name, its file status when indexed, see
# _record_status, and when its files were uploaded), and one row per file of
# the records taken as uploaded, with its fingerprint as 16 bytes
_TABLES = """
CREATE TABLE records (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL,
  uploaded_at REAL
);
CREATE TABLE files (
  record_id INTEGER NOT NULL,
  filesize INTEGER NOT NULL,
  fingerprint BLOB NOT NULL
)
"""
_INDEXES = """
CREATE INDEX IF NOT EXISTS files_by_size ON files (filesize);
CREATE INDEX IF NOT EXISTS files_by_fingerprint ON files (fingerprint);
CREATE INDEX IF NOT EXISTS files_by_record ON files (record_id)
"""

# With this many records to index, and more than are indexed (when the index
# is built), the indexes are made after the files are inserted: it's faster
_BULK_RECORD_COUNT = 1000


def open_uploaded_files() -> history.UploadedFilesLookup | None:
    """
    Open the files recorded in the upload history to look files up, or return
    None if there is no upload history. Close it when done.
    """
    if not constants.MAPILLARY_UPLOAD_HISTORY_PATH:
        return None

    root = history._uploaded_files_dir()
    if not root.is_dir():
        # Nothing uploaded yet
        return history.UploadedFiles()

    try:
        return UploadedFilesIndex.open(root)
    except (OSError, sqlite3.Error) as ex:
        LOG.warning(
            "Not using the upload history index in %s, reading every record: %s",
            root,
            ex,
        )
        return history.read_uploaded_files()


class UploadedFilesIndex:
    """
    The files recorded in the upload history, looked up in the index. If a
    lookup fails, every record is read, and used for the rest of the run.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        # The files uploaded since the index was opened
        self._added = history.UploadedFiles()
        # Every record, read if a lookup in the index failed
        self._read: history.UploadedFiles | None = None

    @classmethod
    def open(cls, root: Path) -> UploadedFilesIndex:
        path = root.joinpath(INDEX_FILENAME)
        try:
            conn = _open_and_update(path, root)
        except sqlite3.DatabaseError as ex:
            # An index left read-only, like after a run as another user, is
            # rebuilt if this process may replace it
            if not (
                _is_corrupt(ex) or (_is_read_only(ex) and os.access(root, os.W_OK))
            ):
                raise
            LOG.warning("Rebuilding the upload history index %s: %s", path, ex)
            _remove(path)
            conn = _open_and_update(path, root)
        conn.execute(f"PRAGMA busy_timeout = {int(LOOKUP_TIMEOUT_SECONDS * 1000)}")
        return cls(conn)

    def find(
        self, path: Path, fingerprints: dict[Path, str] | None = None
    ) -> str | None:
        """
        Return the fingerprint of the file if it was uploaded, or None. The
        file is read only when an uploaded file had the same size. Computed
        fingerprints are kept in the fingerprints given, by path.
        """
        filesize = os.path.getsize(path)
        if filesize not in self._added.sizes and not self._lookup(
            "SELECT 1 FROM files WHERE filesize = ? LIMIT 1",
            (filesize,),
            lambda read: filesize in read.sizes,
        ):
            return None
        file_fingerprint = None if fingerprints is None else fingerprints.get(path)
        if file_fingerprint is None:
            file_fingerprint = fingerprint.fingerprint_file(path)
            if fingerprints is not None:
                fingerprints[path] = file_fingerprint
        if file_fingerprint not in self._added.uploaded_at and not self._lookup(
            "SELECT 1 FROM files WHERE fingerprint = ? LIMIT 1",
            (bytes.fromhex(file_fingerprint),),
            lambda read: file_fingerprint in read.uploaded_at,
        ):
            return None
        return file_fingerprint

    def last_uploaded_at(self, file_fingerprint: str) -> float | None:
        """When the file of the fingerprint was last uploaded, if known"""
        indexed = self._lookup(
            "SELECT MAX(records.uploaded_at) FROM files"
            " JOIN records ON records.id = files.record_id"
            " WHERE files.fingerprint = ?",
            (bytes.fromhex(file_fingerprint),),
            lambda read: read.last_uploaded_at(file_fingerprint),
            scalar=True,
        )
        times = [
            uploaded_at
            for uploaded_at in [indexed, self._added.last_uploaded_at(file_fingerprint)]
            if uploaded_at is not None
        ]
        return max(times, default=None)

    def add(
        self, files: T.Iterable[history.UploadedFile], uploaded_at: float | None
    ) -> None:
        # Their record is indexed the next time the index is opened
        self._added.add(files, uploaded_at)

    def close(self) -> None:
        self._conn.close()

    def _lookup(
        self,
        query: str,
        parameters: tuple,
        in_read: T.Callable[[history.UploadedFiles], T.Any],
        scalar: bool = False,
    ) -> T.Any:
        """
        The value of the query (whether it has a row, or with scalar its
        value), or of in_read on every record read if the index fails
        """
        if self._read is None:
            try:
                row = self._conn.execute(query, parameters).fetchone()
            except sqlite3.DatabaseError as ex:
                LOG.warning(
                    "Failed to look files up in the upload history index, reading every record: %s",
                    ex,
                )
                self._read = history.read_uploaded_files() or history.UploadedFiles()
            else:
                return row[0] if scalar else row is not None
        return in_read(self._read)


def _is_corrupt(ex: sqlite3.DatabaseError) -> bool:
    """Whether the index is not a database or is damaged, not unavailable"""
    # The error codes are known from Python 3.11
    code = getattr(ex, "sqlite_errorcode", None)
    if code is not None and code & 0xFF in [
        11,  # SQLITE_CORRUPT
        26,  # SQLITE_NOTADB
    ]:
        return True
    message = str(ex).lower()
    return any(
        text in message
        for text in [
            "file is not a database",
            "malformed",
            "no such table",
            "no such column",
        ]
    )


def _is_read_only(ex: sqlite3.DatabaseError) -> bool:
    code = getattr(ex, "sqlite_errorcode", None)
    if code is not None and code & 0xFF == 8:  # SQLITE_READONLY
        return True
    return "readonly" in str(ex).lower()


def _remove(path: Path) -> None:
    for suffix in ["", "-journal", "-wal", "-shm"]:
        try:
            os.remove(f"{path}{suffix}")
        except FileNotFoundError:
            pass


def _open_and_update(path: Path, root: Path) -> sqlite3.Connection:
    # Autocommit: the transactions are begun explicitly
    conn = sqlite3.connect(
        str(path), timeout=LOCK_TIMEOUT_SECONDS, isolation_level=None
    )
    try:
        # Lookups are not blocked while another process updates the index
        conn.execute("PRAGMA journal_mode = WAL")
        # The write-ahead log is cut back to 16 MB once it is checkpointed
        conn.execute("PRAGMA journal_size_limit = 16777216")
        _update(conn, root)
    except BaseException:
        conn.close()
        raise
    return conn


def _record_status(entry: os.DirEntry[str]) -> str:
    """
    What changes when a record is written: its size, modification and change
    times, and file ID. Records are written to a new file (see
    history.write_uploaded_files), so the file ID changes too, except on
    Windows, where reading it costs a system call per record.
    """
    stat = entry.stat()
    inode = 0 if sys.platform == "win32" else entry.inode()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}:{inode}"


def _list_records(root: Path) -> dict[str, str]:
    """The status of each record (see _record_status), by its name"""
    records: dict[str, str] = {}
    with os.scandir(root) as folders:
        for folder in folders:
            if not folder.is_dir():
                continue
            with os.scandir(folder.path) as entries:
                for entry in entries:
                    if entry.name.endswith(".json") and entry.is_file():
                        records[f"{folder.name}/{entry.name}"] = _record_status(entry)
    return records


def _update(conn: sqlite3.Connection, root: Path) -> None:
    """Index the records added or changed since, and drop the deleted ones"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        (version,) = conn.execute("PRAGMA user_version").fetchone()
        if version != SCHEMA_VERSION:
            for (table,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall():
                conn.execute(f'DROP TABLE "{table}"')
            for statement in _TABLES.split(";"):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        # Listed while no other process updates the index
        on_disk = _list_records(root)
        indexed = {
            name: (record_id, status)
            for record_id, name, status in conn.execute(
                "SELECT id, name, status FROM records"
            )
        }
        kept = 0
        for name, (record_id, status) in indexed.items():
            if on_disk.get(name) == status:
                kept += 1
            else:
                conn.execute("DELETE FROM files WHERE record_id = ?", (record_id,))
                conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        to_index = [
            (name, status)
            for name, status in on_disk.items()
            if name not in indexed or indexed[name][1] != status
        ]
        if len(to_index) >= _BULK_RECORD_COUNT and len(to_index) > kept:
            LOG.info(
                "Indexing %d records of the upload history: it's done once",
                len(to_index),
            )
            for (index,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'files_by_%'"
            ).fetchall():
                conn.execute(f'DROP INDEX "{index}"')
        for name, status in to_index:
            files, uploaded_at = _read_record(root.joinpath(name))
            record_id = conn.execute(
                "INSERT INTO records (name, status, uploaded_at) VALUES (?, ?, ?)",
                (name, status, uploaded_at),
            ).lastrowid
            conn.executemany(
                "INSERT INTO files (record_id, filesize, fingerprint) VALUES (?, ?, ?)",
                [
                    (record_id, file.filesize, bytes.fromhex(file.fingerprint))
                    for file in files
                ],
            )
        for statement in _INDEXES.split(";"):
            conn.execute(statement)
        conn.execute("COMMIT")
    except BaseException:
        # SQLite rolls back by itself after some errors, like a full disk
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _read_record(path: Path) -> tuple[list[history.UploadedFile], float | None]:
    """
    The files of a record, if taken as uploaded, and when they were uploaded.
    A record that can't be read is indexed without files, so that it is not
    read again until it changes.
    """
    try:
        with path.open("r", encoding="utf-8") as fp:
            record = json.load(fp)
    except (OSError, UnicodeError, json.JSONDecodeError) as ex:
        LOG.warning("Failed to read upload history %s: %s", path, ex)
        return [], None
    if history.is_unfinished_upload(record):
        LOG.info(
            "Not taken as uploaded: the upload in the history record %s was not finished",
            path,
        )
        return [], None
    parsed = history.parse_uploaded_files_record(record)
    if parsed is None:
        LOG.warning("Invalid upload history record %s", path)
        return [], None
    return parsed
