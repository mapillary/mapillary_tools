# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Fingerprints identify files in the upload history without reading them whole.

A fingerprint is a BLAKE2b hash of the file size and of three blocks of the
file: at the start, in the middle and at the end. A file no larger than the
three blocks is hashed whole. Every block of a compressed image or video
differs from one capture to another, and an MP4 index sits at one end of the
file, so two different captures of the same size do not share a fingerprint
in practice. Computing one takes three small reads, whatever the file size.
"""

from __future__ import annotations

import hashlib
import os
import typing as T
from pathlib import Path

BLOCK_SIZE = 64 * 1024

# Hashed along, so that no other hash of the same bytes is taken for a
# fingerprint, and a new way to fingerprint can be told apart
_PERSONALIZATION = b"mly-fingerprint1"

FINGERPRINT_LENGTH = 32


def fingerprint_file(path: Path) -> str:
    """Return the fingerprint of the file, as 32 hexadecimal digits"""
    hasher = hashlib.blake2b(digest_size=16, person=_PERSONALIZATION)
    with path.open("rb") as fp:
        size = os.fstat(fp.fileno()).st_size
        hasher.update(size.to_bytes(8, "little"))
        if size <= 3 * BLOCK_SIZE:
            hasher.update(fp.read())
        else:
            for offset in (0, (size - BLOCK_SIZE) // 2, size - BLOCK_SIZE):
                fp.seek(offset)
                hasher.update(fp.read(BLOCK_SIZE))
    return hasher.hexdigest()


def combine_fingerprints(fingerprints: T.Iterable[str]) -> str:
    """Return a fingerprint for files taken together, in this order"""
    hasher = hashlib.blake2b(digest_size=16, person=_PERSONALIZATION)
    for fingerprint in fingerprints:
        hasher.update(fingerprint.encode("ascii"))
    return hasher.hexdigest()


_LOWERCASE_HEXDIGITS = frozenset("0123456789abcdef")


def is_fingerprint(value: T.Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == FINGERPRINT_LENGTH
        and set(value) <= _LOWERCASE_HEXDIGITS
    )
