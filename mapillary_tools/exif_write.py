# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

# pyre-ignore-all-errors[5, 21, 24]
from __future__ import annotations

import datetime
import io
import json
import logging
import math
import struct
from fractions import Fraction
from pathlib import Path
from typing import Any, BinaryIO, Sequence

import piexif
from piexif._common import merge_segments, split_into_segments


LOG = logging.getLogger(__name__)

# Matches FFmpeg jpegapp: u32be length does not include the 4-byte prefix.
JPEGAPP_MAX_RECORD = 16 * 1024 * 1024
_JPEG_HEADER_CHUNK = 64 * 1024
_JPEG_HEADER_MAX = 2 * 1024 * 1024


def _try_split_jpeg_segments(data: bytes) -> list[bytes] | None:
    """None if *data* is not yet a complete JPEG prefix through SOS."""
    try:
        segments = split_into_segments(data)
    except (piexif.InvalidImageDataError, struct.error, ValueError):
        return None
    if not segments or segments[-1][:2] != b"\xff\xda":
        return None
    return segments


def jpeg_header_segments(fp: BinaryIO) -> tuple[list[bytes], int]:
    """SOI..last marker before SOS via piexif, and file offset of SOS."""
    buf = bytearray()
    while True:
        chunk = fp.read(_JPEG_HEADER_CHUNK)
        if not chunk:
            raise ValueError("Truncated JPEG: no SOS marker")
        buf += chunk
        segments = _try_split_jpeg_segments(bytes(buf))
        if segments is not None:
            header = segments[:-1]
            return header, sum(len(s) for s in header)
        if len(buf) >= _JPEG_HEADER_MAX:
            raise ValueError("JPEG header too large to split before SOS")


class JpegApp1RewriteStream(io.RawIOBase):
    """Seekable JPEG: piexif-merged prefix (new APP1) plus original bytes from SOS."""

    def __init__(self, path: Path, prefix: bytes, rest_offset: int, app1: bytes):
        super().__init__()
        self.prefix = prefix
        self.app1 = app1
        self._rest_offset = rest_offset
        self._fp = path.open("rb")
        rest_len = max(0, path.stat().st_size - rest_offset)
        self._size = len(prefix) + rest_len
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            pos = offset
        elif whence == io.SEEK_CUR:
            pos = self._pos + offset
        elif whence == io.SEEK_END:
            pos = self._size + offset
        else:
            raise ValueError(f"invalid whence {whence}")
        if pos < 0:
            raise ValueError("negative seek")
        self._pos = pos
        return self._pos

    def read(self, size: int = -1) -> bytes:
        if self.closed:
            raise ValueError("read from closed stream")
        remaining = self._size - self._pos
        if remaining <= 0:
            return b""
        if size is None or size < 0:
            size = remaining
        size = min(size, remaining)
        out = bytearray()
        while size > 0:
            if self._pos < len(self.prefix):
                n = min(size, len(self.prefix) - self._pos)
                out += self.prefix[self._pos : self._pos + n]
                self._pos += n
                size -= n
                continue
            file_pos = self._rest_offset + (self._pos - len(self.prefix))
            self._fp.seek(file_pos)
            chunk = self._fp.read(size)
            if not chunk:
                break
            out += chunk
            self._pos += len(chunk)
            size -= len(chunk)
        return bytes(out)

    def close(self) -> None:
        if not self.closed:
            self._fp.close()
        super().close()


def pack_jpeg_app_record(payload: bytes) -> bytes:
    """One sidecar record: big-endian length plus APP-segment bytes."""
    if len(payload) > JPEGAPP_MAX_RECORD:
        raise ValueError(
            f"JPEG APP sidecar record is {len(payload)} bytes; max is {JPEGAPP_MAX_RECORD}"
        )
    return struct.pack(">I", len(payload)) + payload


def write_jpeg_app_sidecar(path: Path, payloads: Sequence[bytes]) -> None:
    """Write length-prefixed JPEG APP records, one per output JPEG, encode order."""
    with open(path, "wb") as fp:
        for payload in payloads:
            fp.write(pack_jpeg_app_record(payload))


class ExifEdit:
    _filename_or_bytes: str | bytes
    _ef: dict[str, Any]

    def __init__(self, filename_or_bytes: Path | bytes | None) -> None:
        """Initialize the object"""
        if filename_or_bytes is None:
            self._filename_or_bytes = b""
            self._ef = {
                "0th": {},
                "Exif": {},
                "GPS": {},
                "Interop": {},
                "1st": {},
                "thumbnail": None,
            }
            return
        if isinstance(filename_or_bytes, Path):
            # make sure filename is resolved to avoid to be interpretted as bytes in piexif
            # see https://github.com/hMatoba/Piexif/issues/124
            self._filename_or_bytes = str(filename_or_bytes.resolve())
        else:
            self._filename_or_bytes = filename_or_bytes
        loaded = piexif.load(self._filename_or_bytes)
        if not loaded:
            loaded = {
                "0th": {},
                "Exif": {},
                "GPS": {},
                "Interop": {},
                "1st": {},
                "thumbnail": None,
            }
        self._ef = loaded

    @staticmethod
    def decimal_to_dms(
        value: float,
    ) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
        """Convert decimal position to Exif degrees, minutes, and seconds rationals"""

        deg: int = int(value)
        min: int = int(value := (value - deg) * 60)
        sec: float = (value - min) * 60

        return (
            (deg, 1),
            (min, 1),
            (Fraction.from_float(sec).limit_denominator().as_integer_ratio()),
        )

    def add_image_description(self, data: dict) -> None:
        """Add a dict to image description."""
        self._ef["0th"][piexif.ImageIFD.ImageDescription] = json.dumps(
            data, sort_keys=True, separators=(",", ":")
        )

    def add_orientation(self, orientation: int) -> None:
        """Add image orientation to image."""
        if orientation not in range(1, 9):
            raise ValueError(f"orientation value {orientation} must be in range(1, 9)")
        self._ef["0th"][piexif.ImageIFD.Orientation] = orientation

    def add_date_time_original(self, dt: datetime.datetime) -> None:
        """Add date time original."""
        self._ef["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt.strftime(
            "%Y:%m:%d %H:%M:%S"
        )
        self._ef["Exif"][piexif.ExifIFD.SubSecTimeOriginal] = dt.strftime("%f")
        if dt.tzinfo is not None:
            # UTC offset in the form ±HHMM[SS[.ffffff]] (empty string if the object is naive).
            # (empty), +0000, -0400, +1030, +063415, -030712.345216
            offset_str = dt.strftime("%z")
            if offset_str:
                sign, hh, mm = offset_str[0], offset_str[1:3], offset_str[3:5]
                assert sign in ["+", "-"], sign
                assert hh.isdigit(), hh
                assert mm.isdigit(), mm
                self._ef["Exif"][piexif.ExifIFD.OffsetTimeOriginal] = f"{sign}{hh}:{mm}"
            else:
                if piexif.ExifIFD.OffsetTimeOriginal in self._ef["Exif"]:
                    del self._ef["Exif"][piexif.ExifIFD.OffsetTimeOriginal]
        else:
            if piexif.ExifIFD.OffsetTimeOriginal in self._ef["Exif"]:
                del self._ef["Exif"][piexif.ExifIFD.OffsetTimeOriginal]

    def add_gps_datetime(self, dt: datetime.datetime) -> None:
        """Add GPSDateStamp and GPSTimeStamp."""
        dt = dt.astimezone(datetime.timezone.utc)
        # YYYY:MM:DD
        self._ef["GPS"][piexif.GPSIFD.GPSDateStamp] = dt.strftime("%Y:%m:%d")
        self._ef["GPS"][piexif.GPSIFD.GPSTimeStamp] = (
            (dt.hour, 1),
            (dt.minute, 1),
            (
                Fraction.from_float(dt.second + dt.microsecond / 1e6)
                .limit_denominator()
                .as_integer_ratio()
            ),
        )
        if LOG.isEnabledFor(logging.DEBUG):
            LOG.debug(
                'GPSDateStamp: "%s"\tGPSTimeStamp: %s',
                self._ef["GPS"][piexif.GPSIFD.GPSDateStamp],
                self._ef["GPS"][piexif.GPSIFD.GPSTimeStamp],
            )

    def add_lat_lon(self, lat: float, lon: float) -> None:
        """Add lat, lon to gps (lat, lon in float)."""

        self._ef["GPS"][piexif.GPSIFD.GPSLatitudeRef] = "N" if lat > 0 else "S"
        self._ef["GPS"][piexif.GPSIFD.GPSLatitude] = ExifEdit.decimal_to_dms(
            math.fabs(lat)
        )
        self._ef["GPS"][piexif.GPSIFD.GPSLongitudeRef] = "E" if lon > 0 else "W"
        self._ef["GPS"][piexif.GPSIFD.GPSLongitude] = ExifEdit.decimal_to_dms(
            math.fabs(lon)
        )
        if LOG.isEnabledFor(logging.DEBUG):
            LOG.debug(
                "GPSLatitude: %s\tGPSLongitude: %s",
                self._ef["GPS"][piexif.GPSIFD.GPSLatitude],
                self._ef["GPS"][piexif.GPSIFD.GPSLongitude],
            )

    def add_altitude(self, altitude: float) -> None:
        """Add altitude."""

        ref = 0 if altitude > 0 else 1
        self._ef["GPS"][piexif.GPSIFD.GPSAltitude] = (
            Fraction.from_float(math.fabs(altitude))
            .limit_denominator()
            .as_integer_ratio()
        )
        self._ef["GPS"][piexif.GPSIFD.GPSAltitudeRef] = ref
        if LOG.isEnabledFor(logging.DEBUG):
            LOG.debug(
                'GPSAltitudeRef: "%s"\tGPSAltitude: %s',
                self._ef["GPS"][piexif.GPSIFD.GPSAltitudeRef],
                self._ef["GPS"][piexif.GPSIFD.GPSAltitude],
            )

    def add_direction(self, direction: float, ref: str = "T") -> None:
        """Add image direction."""

        # normalize direction
        direction = math.fmod(direction, 360.0)
        self._ef["GPS"][piexif.GPSIFD.GPSImgDirection] = (
            Fraction.from_float(direction).limit_denominator().as_integer_ratio()
        )
        self._ef["GPS"][piexif.GPSIFD.GPSImgDirectionRef] = ref
        if LOG.isEnabledFor(logging.DEBUG):
            LOG.debug(
                'GPSImgDirectionRef: "%s"\tGPSImgDirection: %s',
                self._ef["GPS"][piexif.GPSIFD.GPSImgDirectionRef],
                self._ef["GPS"][piexif.GPSIFD.GPSImgDirection],
            )

    def add_make(self, make: str) -> None:
        if not make:
            raise ValueError("Make cannot be empty")
        self._ef["0th"][piexif.ImageIFD.Make] = make

    def add_model(self, model: str) -> None:
        if not model:
            raise ValueError("Model cannot be empty")
        self._ef["0th"][piexif.ImageIFD.Model] = model

    def _safe_dump(self) -> bytes:
        TRUSTED_TAGS = [
            piexif.ExifIFD.DateTimeOriginal,
            piexif.GPSIFD.GPSAltitude,
            piexif.GPSIFD.GPSAltitudeRef,
            piexif.GPSIFD.GPSImgDirection,
            piexif.GPSIFD.GPSImgDirection,
            piexif.GPSIFD.GPSImgDirectionRef,
            piexif.GPSIFD.GPSImgDirectionRef,
            piexif.GPSIFD.GPSLatitude,
            piexif.GPSIFD.GPSLatitudeRef,
            piexif.GPSIFD.GPSLongitude,
            piexif.GPSIFD.GPSLongitudeRef,
            piexif.ImageIFD.ImageDescription,
            piexif.ImageIFD.Orientation,
        ]

        thumbnail_removed = False

        while True:
            try:
                exif_bytes = piexif.dump(self._ef)
            except piexif.InvalidImageDataError as exc:
                if thumbnail_removed:
                    raise exc
                LOG.debug(
                    "InvalidImageDataError on dumping -- removing thumbnail and 1st: %s",
                    exc,
                )
                # workaround: https://github.com/hMatoba/Piexif/issues/30
                del self._ef["thumbnail"]
                del self._ef["1st"]
                thumbnail_removed = True
                # retry later
            except ValueError as exc:
                # workaround: https://github.com/hMatoba/Piexif/issues/95
                # a sample message: "dump" got wrong type of exif value.\n41729 in Exif IFD. Got as <class 'int'>.
                message = str(exc)
                if "got wrong type of exif value" in message:
                    split = message.split("\n")
                    LOG.debug(
                        "Found invalid EXIF tag -- removing it and retry: %s", message
                    )
                    try:
                        tag = int(split[1].split()[0])
                        ifd = split[1].split()[2]
                    except Exception:
                        raise exc
                    if tag in TRUSTED_TAGS:
                        raise exc
                    else:
                        del self._ef[ifd][tag]
                        # retry later
                elif "thumbnail is too large" in message.lower():
                    # Handle oversized thumbnails (max 64kB per EXIF spec)
                    if thumbnail_removed:
                        raise exc
                    LOG.debug(
                        "Thumbnail too large (max 64kB) -- removing thumbnail and 1st: %s",
                        exc,
                    )
                    del self._ef["thumbnail"]
                    del self._ef["1st"]
                    thumbnail_removed = True
                    # retry later
                else:
                    raise exc
            except Exception as exc:
                zeroth_ifd = self._ef.get("0th", {})
                # workaround: https://github.com/mapillary/mapillary_tools/issues/662
                if piexif.ImageIFD.AsShotNeutral in zeroth_ifd:
                    del zeroth_ifd[piexif.ImageIFD.AsShotNeutral]
                    assert piexif.ImageIFD.AsShotNeutral not in zeroth_ifd
                else:
                    raise exc
            else:
                break

        return exif_bytes

    def app1_segment(self) -> bytes:
        """EXIF as a JPEG APP1 segment (``FF E1`` + length + TIFF/Exif payload)."""
        dump = self._safe_dump()
        return self._wrap_exif_app1(dump)

    @staticmethod
    def _wrap_exif_app1(exif: bytes) -> bytes:
        # JPEG APP length is 16-bit and includes the 2 length bytes, not the marker.
        if len(exif) + 2 > 65535:
            raise ValueError(f"EXIF APP1 segment too large: {len(exif) + 2} bytes")
        return b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif

    def open_rewritten_stream(self) -> JpegApp1RewriteStream:
        """APP1 via piexif merge; SOS..EOI read from the original file.

        JPEG marker splitting stays in piexif (``split_into_segments`` /
        ``merge_segments``). The entropy-coded scan is not copied in RAM.
        """
        if not isinstance(self._filename_or_bytes, str):
            raise ValueError("APP1 stream rewrite needs a JPEG path")
        path = Path(self._filename_or_bytes)
        app1 = self._wrap_exif_app1(self._safe_dump())
        with path.open("rb") as fp:
            header_segs, rest_offset = jpeg_header_segments(fp)
        prefix = merge_segments(list(header_segs), app1)
        return JpegApp1RewriteStream(path, prefix, rest_offset, app1)

    def dump_image_bytes(self, *, stream: bool = True) -> bytes:
        if stream and isinstance(self._filename_or_bytes, str):
            try:
                with self.open_rewritten_stream() as fp:
                    return fp.read()
            except Exception:
                LOG.debug(
                    "APP1 stream rewrite failed, falling back to piexif.insert",
                    exc_info=True,
                )
        exif_bytes = self._safe_dump()
        with io.BytesIO() as output:
            piexif.insert(exif_bytes, self._filename_or_bytes, output)
            return output.read()

    def write(self, filename: Path | None = None) -> None:
        """Save exif data to file."""
        if filename is None:
            if not isinstance(self._filename_or_bytes, str):
                raise ValueError("Unable to write image into bytes")
            filename = Path(self._filename_or_bytes)
        # make sure filename is resolved to avoid to be interpretted as bytes in piexif
        filename = filename.resolve()

        exif_bytes = self._safe_dump()

        if isinstance(self._filename_or_bytes, bytes):
            img = self._filename_or_bytes
        else:
            with open(self._filename_or_bytes, "rb") as fp:
                img = fp.read()

        piexif.insert(exif_bytes, img, str(filename))
