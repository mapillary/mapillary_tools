# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""Generate JPEGs whose EXIF piexif can *load* but cannot *re-dump*.

These fixtures drive the recovery logic in ``ExifEdit._safe_dump``. Neither PIL
nor ``piexif.dump`` can produce them (both normalize or reject the offending
data), so the EXIF blocks are assembled by hand.

Wrong-type fixtures store an ASCII tag with TIFF type SHORT, so piexif decodes
it as an ``int`` but on dump expects a ``str`` and raises ``"got wrong type of
exif value"``:

- ``corrupt_exif_wrong_type.jpg`` uses Software (0x0131), a *non-trusted* tag,
  so _safe_dump strips it and retries -> dump succeeds.
- ``corrupt_exif_trusted_wrong_type.jpg`` uses ImageDescription (0x010E), a
  *trusted* tag, so _safe_dump must re-raise instead of silently dropping it.

The large-thumbnail fixture embeds a thumbnail above piexif's 64000-byte dump
limit (but still within a single JPEG APP1 segment), so _safe_dump drops the
thumbnail and the 1st IFD and retries:

- ``corrupt_exif_large_thumbnail.jpg``

Run from the repo root to regenerate the committed fixtures:

    uv run python tests/unit/generate_corrupt_exif_image.py
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

import piexif
from PIL import Image

_TYPE_SHORT = 3  # write the value as a SHORT regardless of the tag's real type

_SOFTWARE_TAG = 0x0131  # non-trusted ASCII tag -> _safe_dump strips and retries
_IMAGE_DESCRIPTION_TAG = 0x010E  # trusted ASCII tag -> _safe_dump re-raises

# piexif rejects thumbnails larger than 64000 bytes on dump; this size is over
# that limit yet small enough to fit in a JPEG APP1 segment (max 65535 bytes).
_LARGE_THUMBNAIL_SIZE = 64500


def _build_one_entry_tiff(tag: int) -> bytes:
    """Little-endian TIFF with one IFD0 entry: ``tag`` stored as a SHORT."""
    header = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)  # IFD0 at offset 8
    entry_count = struct.pack("<H", 1)
    entry = (
        struct.pack("<H", tag)
        + struct.pack("<H", _TYPE_SHORT)
        + struct.pack("<I", 1)  # count
        + struct.pack("<I", 123)  # inline value
    )
    next_ifd = struct.pack("<I", 0)
    return header + entry_count + entry + next_ifd


def build_wrong_type_exif_jpeg(tag: int) -> bytes:
    """Return JPEG bytes with a loadable-but-undumpable EXIF block for ``tag``."""
    base = Image.new("RGB", (32, 32), "green")
    base_buf = io.BytesIO()
    base.save(base_buf, "JPEG")

    exif_bytes = b"Exif\x00\x00" + _build_one_entry_tiff(tag)
    out = io.BytesIO()
    piexif.insert(exif_bytes, base_buf.getvalue(), out)
    return out.getvalue()


def _make_oversized_thumbnail() -> bytes:
    """A deterministic blob over piexif's 64000-byte thumbnail limit."""
    tiny = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(tiny, "JPEG")
    jpeg = tiny.getvalue()
    return jpeg + b"\x00" * (_LARGE_THUMBNAIL_SIZE - len(jpeg))


def _build_thumbnail_tiff(thumbnail: bytes) -> bytes:
    """Little-endian TIFF with an empty IFD0 pointing to a thumbnail in IFD1."""
    thumb_offset = 44  # bytes consumed by the header + IFD0 + IFD1 below
    out = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)  # IFD0 at offset 8
    out += struct.pack("<H", 0)  # IFD0: no entries
    out += struct.pack("<I", 14)  # IFD0 next-IFD offset -> IFD1 at offset 14
    out += struct.pack("<H", 2)  # IFD1: two entries
    out += (
        struct.pack("<H", 0x0201)  # JPEGInterchangeFormat (thumbnail offset)
        + struct.pack("<H", 4)  # LONG
        + struct.pack("<I", 1)
        + struct.pack("<I", thumb_offset)
    )
    out += (
        struct.pack("<H", 0x0202)  # JPEGInterchangeFormatLength (thumbnail length)
        + struct.pack("<H", 4)  # LONG
        + struct.pack("<I", 1)
        + struct.pack("<I", len(thumbnail))
    )
    out += struct.pack("<I", 0)  # IFD1 next-IFD offset = 0
    assert len(out) == thumb_offset, len(out)
    return out + thumbnail


def build_large_thumbnail_exif_jpeg() -> bytes:
    """Return JPEG bytes whose EXIF carries a thumbnail too large to re-dump."""
    base = Image.new("RGB", (100, 100), "red")
    base_buf = io.BytesIO()
    base.save(base_buf, "JPEG")

    exif_bytes = b"Exif\x00\x00" + _build_thumbnail_tiff(_make_oversized_thumbnail())
    out = io.BytesIO()
    piexif.insert(exif_bytes, base_buf.getvalue(), out)
    return out.getvalue()


def main() -> None:
    data_dir = Path(__file__).resolve().parent / "data"
    wrong_type_fixtures = {
        "corrupt_exif_wrong_type.jpg": _SOFTWARE_TAG,
        "corrupt_exif_trusted_wrong_type.jpg": _IMAGE_DESCRIPTION_TAG,
    }
    for filename, tag in wrong_type_fixtures.items():
        out_path = data_dir / filename
        out_path.write_bytes(build_wrong_type_exif_jpeg(tag))
        print(f"Wrote {out_path}")

    large_thumb_path = data_dir / "corrupt_exif_large_thumbnail.jpg"
    large_thumb_path.write_bytes(build_large_thumbnail_exif_jpeg())
    print(f"Wrote {large_thumb_path}")


if __name__ == "__main__":
    main()
