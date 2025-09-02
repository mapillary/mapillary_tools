import os
import sqlite3
from collections.abc import MutableMapping
from contextlib import closing, suppress
from pathlib import Path

BUILD_TABLE = """
  CREATE TABLE IF NOT EXISTS Dict (
    key BLOB UNIQUE NOT NULL,
    value BLOB NOT NULL
  )
"""
GET_SIZE = "SELECT COUNT (key) FROM Dict"
LOOKUP_KEY = "SELECT value FROM Dict WHERE key = CAST(? AS BLOB)"
STORE_KV = "REPLACE INTO Dict (key, value) VALUES (CAST(? AS BLOB), CAST(? AS BLOB))"
DELETE_KEY = "DELETE FROM Dict WHERE key = CAST(? AS BLOB)"
ITER_KEYS = "SELECT key FROM Dict"


_ERR_CLOSED = "KeyValueStore object has already been closed"


def _normalize_uri(path):
    path = Path(path)
    uri = path.absolute().as_uri()
    while "//" in uri:
        uri = uri.replace("//", "/")
    return uri


class KeyValueStore(MutableMapping):
    def __init__(self, path, /, *, flag="r", mode=0o666):
        """Open a key-value database and return the object.

        The 'path' parameter is the name of the database file.

        The optional 'flag' parameter can be one of ...:
            'r' (default): open an existing database for read only access
            'w': open an existing database for read/write access
            'c': create a database if it does not exist; open for read/write access
            'n': always create a new, empty database; open for read/write access

        The optional 'mode' parameter is the Unix file access mode of the database;
        only used when creating a new database. Default: 0o666.
        """
        path = os.fsdecode(path)
        if flag == "r":
            flag = "ro"
        elif flag == "w":
            flag = "rw"
        elif flag == "c":
            flag = "rwc"
            Path(path).touch(mode=mode, exist_ok=True)
        elif flag == "n":
            flag = "rwc"
            Path(path).unlink(missing_ok=True)
            Path(path).touch(mode=mode)
        else:
            raise ValueError(f"Flag must be one of 'r', 'w', 'c', or 'n', not {flag!r}")

        # We use the URI format when opening the database.
        uri = _normalize_uri(path)
        uri = f"{uri}?mode={flag}"

        self._cx = sqlite3.connect(uri, autocommit=True, uri=True)

        # This is an optimization only; it's ok if it fails.
        with suppress(sqlite3.OperationalError):
            self._cx.execute("PRAGMA journal_mode = wal")

        if flag == "rwc":
            self._execute(BUILD_TABLE)

    def _execute(self, *args, **kwargs):
        return closing(self._cx.execute(*args, **kwargs))

    def __len__(self):
        with self._execute(GET_SIZE) as cu:
            row = cu.fetchone()
        return row[0]

    def __getitem__(self, key):
        with self._execute(LOOKUP_KEY, (key,)) as cu:
            row = cu.fetchone()
        if not row:
            raise KeyError(key)
        return row[0]

    def __setitem__(self, key, value):
        self._execute(STORE_KV, (key, value))

    def __delitem__(self, key):
        with self._execute(DELETE_KEY, (key,)) as cu:
            if not cu.rowcount:
                raise KeyError(key)

    def __iter__(self):
        with self._execute(ITER_KEYS) as cu:
            for row in cu:
                yield row[0]

    def close(self):
        self._cx.close()

    def keys(self):
        return list(super().keys())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
