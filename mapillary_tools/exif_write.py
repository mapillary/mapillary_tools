# pyre-ignore-all-errors[5, 21, 24]

import datetime
import io
import json
import logging
import math
import typing as T

import piexif


LOG = logging.getLogger(__name__)


class ExifEdit:
    _filename_or_bytes: T.Union[str, bytes]

    def __init__(self, filename_or_bytes: T.Union[str, bytes]) -> None:
        """Initialize the object"""
        self._filename_or_bytes = filename_or_bytes
        self._ef: T.Dict = piexif.load(filename_or_bytes)

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

    def add_date_time_original(
        self, date_time: datetime.datetime, time_format: str = "%Y:%m:%d %H:%M:%S.%f"
    ) -> None:
        """Add date time original."""
        DateTimeOriginal = date_time.strftime(time_format)[:-3]
        self._ef["Exif"][piexif.ExifIFD.DateTimeOriginal] = DateTimeOriginal

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
            else:
                break

        return exif_bytes

    def dump_image_bytes(self) -> bytes:
        exif_bytes = self._safe_dump()
        output = io.BytesIO()
        piexif.insert(exif_bytes, self._filename_or_bytes, output)
        return output.read()

    def write(self, filename: T.Optional[str] = None) -> None:
        """Save exif data to file."""
        if filename is None:
            if isinstance(self._filename_or_bytes, str):
                filename = self._filename_or_bytes
            else:
                raise RuntimeError("Unable to write image into bytes")

        exif_bytes = self._safe_dump()

        if isinstance(self._filename_or_bytes, bytes):
            img = self._filename_or_bytes
        else:
            with open(self._filename_or_bytes, "rb") as fp:
                img = fp.read()

        piexif.insert(exif_bytes, img, filename)
