# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""Generate JPEGs whose EXIF piexif can *load* but cannot *re-dump*.

Each fixture carries a single IFD0 entry whose value is stored with the wrong
TIFF type: an ASCII tag is written as a SHORT, so piexif decodes it as an
``int`` but on dump expects a ``str`` and raises ``"got wrong type of exif
value"``. This drives the recovery logic in ``ExifEdit._safe_dump``:

- ``corrupt_exif_wrong_type.jpg`` uses Software (0x0131), a *non-trusted* tag,
  so _safe_dump strips it and retries -> dump succeeds.
- ``corrupt_exif_trusted_wrong_type.jpg`` uses ImageDescription (0x010E), a
  *trusted* tag, so _safe_dump must re-raise instead of silently dropping it.

Neither PIL nor ``piexif.dump`` can produce such files (both normalize or
reject the malformed value), so the EXIF block is assembled by hand.

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

# (filename, IFD0 tag id) for each fixture.
_SOFTWARE_TAG = 0x0131  # non-trusted ASCII tag -> _safe_dump strips and retries
_IMAGE_DESCRIPTION_TAG = 0x010E  # trusted ASCII tag -> _safe_dump re-raises


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


def main() -> None:
    data_dir = Path(__file__).resolve().parent / "data"
    fixtures = {
        "corrupt_exif_wrong_type.jpg": _SOFTWARE_TAG,
        "corrupt_exif_trusted_wrong_type.jpg": _IMAGE_DESCRIPTION_TAG,
    }
    for filename, tag in fixtures.items():
        out_path = data_dir / filename
        out_path.write_bytes(build_wrong_type_exif_jpeg(tag))
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
