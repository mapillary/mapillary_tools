# pyre-ignore-all-errors[5, 21, 24]

import datetime
import io
import json
import logging
import math
import typing as T
from pathlib import Path

import piexif


LOG = logging.getLogger(__name__)


class ExifEdit:
    _filename_or_bytes: T.Union[str, bytes]

    def __init__(self, filename_or_bytes: T.Union[Path, bytes]) -> None:
        """Initialize the object"""
        if isinstance(filename_or_bytes, Path):
            # make sure filename is resolved to avoid to be interpretted as bytes in piexif
            # see https://github.com/hMatoba/Piexif/issues/124
            self._filename_or_bytes = str(filename_or_bytes.resolve())
        else:
            self._filename_or_bytes = filename_or_bytes
        self._ef: T.Dict = piexif.load(self._filename_or_bytes)

    @staticmethod
    def decimal_to_dms(
        value: float, precision: int
    ) -> T.Tuple[T.Tuple[float, int], T.Tuple[float, int], T.Tuple[float, int]]:
        """
        Convert decimal position to degrees, minutes, seconds in a fromat supported by EXIF
        """
        deg = math.floor(value)
        min = math.floor((value - deg) * 60)
        sec = math.floor((value - deg - min / 60) * 3600 * precision)

        return (deg, 1), (min, 1), (sec, precision)

    def add_image_description(self, data: T.Dict) -> None:
        """Add a dict to image description."""
        self._ef["0th"][piexif.ImageIFD.ImageDescription] = json.dumps(data)

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
            # num / den = (dt.second * 1e6 + dt.microsecond) / 1e6
            (int(dt.second * 1e6 + dt.microsecond), int(1e6)),
        )

    def add_lat_lon(self, lat: float, lon: float, precision: float = 1e7) -> None:
        """Add lat, lon to gps (lat, lon in float)."""
        self._ef["GPS"][piexif.GPSIFD.GPSLatitudeRef] = "N" if lat > 0 else "S"
        self._ef["GPS"][piexif.GPSIFD.GPSLongitudeRef] = "E" if lon > 0 else "W"
        self._ef["GPS"][piexif.GPSIFD.GPSLongitude] = ExifEdit.decimal_to_dms(
            abs(lon), int(precision)
        )
        self._ef["GPS"][piexif.GPSIFD.GPSLatitude] = ExifEdit.decimal_to_dms(
            abs(lat), int(precision)
        )

    def add_altitude(self, altitude: float, precision: int = 100) -> None:
        """Add altitude (pre is the precision)."""
        ref = 0 if altitude > 0 else 1
        self._ef["GPS"][piexif.GPSIFD.GPSAltitude] = (
            int(abs(altitude) * precision),
            precision,
        )
        self._ef["GPS"][piexif.GPSIFD.GPSAltitudeRef] = ref

    def add_direction(
        self, direction: float, ref: str = "T", precision: int = 100
    ) -> None:
        """Add image direction."""
        # normalize direction
        direction = direction % 360.0
        self._ef["GPS"][piexif.GPSIFD.GPSImgDirection] = (
            int(abs(direction) * precision),
            precision,
        )
        self._ef["GPS"][piexif.GPSIFD.GPSImgDirectionRef] = ref

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

    def dump_image_bytes(self) -> bytes:
        exif_bytes = self._safe_dump()
        with io.BytesIO() as output:
            piexif.insert(exif_bytes, self._filename_or_bytes, output)
            return output.read()

    def write(self, filename: T.Optional[Path] = None) -> None:
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
