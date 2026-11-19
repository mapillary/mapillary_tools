# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import os
from pathlib import Path

import pytest
from mapillary_tools import fingerprint

BLOCK = fingerprint.BLOCK_SIZE


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _change_byte(path: Path, offset: int) -> None:
    data = bytearray(path.read_bytes())
    data[offset] ^= 0xFF
    path.write_bytes(bytes(data))


def test_small_file_is_hashed_whole(tmp_path: Path):
    path = _write(tmp_path / "small.jpg", os.urandom(3 * BLOCK))

    expected = hashlib.blake2b(digest_size=16, person=b"mly-fingerprint1")
    expected.update((3 * BLOCK).to_bytes(8, "little"))
    expected.update(path.read_bytes())
    assert fingerprint.fingerprint_file(path) == expected.hexdigest()

    # Any byte counts
    before = fingerprint.fingerprint_file(path)
    _change_byte(path, BLOCK + 10)
    assert fingerprint.fingerprint_file(path) != before


def test_large_file_is_fingerprinted_by_its_start_middle_and_end(tmp_path: Path):
    size = 10 * BLOCK + 123
    path = _write(tmp_path / "video.mp4", os.urandom(size))
    original = fingerprint.fingerprint_file(path)
    assert fingerprint.is_fingerprint(original)

    middle = (size - BLOCK) // 2
    # Bytes outside the three blocks are not read
    for offset in [BLOCK, middle - 1, middle + BLOCK, size - BLOCK - 1]:
        _change_byte(path, offset)
        assert fingerprint.fingerprint_file(path) == original
        _change_byte(path, offset)

    # Bytes in the three blocks are
    for offset in [0, BLOCK - 1, middle, middle + BLOCK - 1, size - BLOCK, size - 1]:
        _change_byte(path, offset)
        assert fingerprint.fingerprint_file(path) != original
        _change_byte(path, offset)

    assert fingerprint.fingerprint_file(path) == original


def test_the_size_is_part_of_the_fingerprint(tmp_path: Path):
    # All three blocks are zeros in both files: only the size differs
    path = _write(tmp_path / "video.mp4", bytes(10 * BLOCK))
    longer = _write(tmp_path / "longer.mp4", bytes(10 * BLOCK + 2))
    assert fingerprint.fingerprint_file(path) != fingerprint.fingerprint_file(longer)


def test_the_same_bytes_have_the_same_fingerprint(tmp_path: Path):
    data = os.urandom(5 * BLOCK)
    first = _write(tmp_path / "GX010001.MP4", data)
    renamed = _write(tmp_path / "renamed.mp4", data)
    assert fingerprint.fingerprint_file(first) == fingerprint.fingerprint_file(renamed)


def test_combine_fingerprints_depends_on_the_order():
    first, second = "0" * 32, "f" * 32
    combined = fingerprint.combine_fingerprints([first, second])
    assert fingerprint.is_fingerprint(combined)
    assert combined != fingerprint.combine_fingerprints([second, first])
    assert combined == fingerprint.combine_fingerprints([first, second])


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0123456789abcdef0123456789abcdef", True),
        ("0123456789ABCDEF0123456789ABCDEF", False),
        ("0123456789abcdef0123456789abcde", False),
        ("0x23456789abcdef0123456789abcdef", False),
        ("0123456789abcdef_123456789abcdef", False),
        (None, False),
        (123, False),
    ],
)
def test_is_fingerprint(value, expected):
    assert fingerprint.is_fingerprint(value) is expected
