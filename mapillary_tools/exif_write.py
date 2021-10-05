import datetime
import json
import io

import piexif

from .geo import decimal_to_dms
from .types import FinalImageDescription


class ExifEdit:
    _filename: str

    def __init__(self, filename: str):
        """Initialize the object"""
        self._filename = filename
        self._ef = piexif.load(filename)

    def add_image_description(self, data: FinalImageDescription) -> None:
        """Add a dict to image description."""
        self._ef["0th"][piexif.ImageIFD.ImageDescription] = json.dumps(data)

    def add_orientation(self, orientation: int) -> None:
        """Add image orientation to image."""
        if orientation not in range(1, 9):
            raise ValueError(f"orientation value {orientation} must be in range(1, 9)")
        self._ef["0th"][piexif.ImageIFD.Orientation] = orientation

    def add_date_time_original(
        self, date_time: datetime.datetime, time_format: str = "%Y:%m:%d %H:%M:%S.%f"
    ):
        """Add date time original."""
        DateTimeOriginal = date_time.strftime(time_format)[:-3]
        self._ef["Exif"][piexif.ExifIFD.DateTimeOriginal] = DateTimeOriginal

    def add_lat_lon(self, lat: float, lon: float, precision: float = 1e7):
        """Add lat, lon to gps (lat, lon in float)."""
        self._ef["GPS"][piexif.GPSIFD.GPSLatitudeRef] = "N" if lat > 0 else "S"
        self._ef["GPS"][piexif.GPSIFD.GPSLongitudeRef] = "E" if lon > 0 else "W"
        self._ef["GPS"][piexif.GPSIFD.GPSLongitude] = decimal_to_dms(
            abs(lon), int(precision)
        )
        self._ef["GPS"][piexif.GPSIFD.GPSLatitude] = decimal_to_dms(
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

    def add_direction(self, direction, ref="T", precision=100):
        """Add image direction."""
        # normalize direction
        direction = direction % 360.0
        self._ef["GPS"][piexif.GPSIFD.GPSImgDirection] = (
            int(abs(direction) * precision),
            precision,
        )
        self._ef["GPS"][piexif.GPSIFD.GPSImgDirectionRef] = ref

    def dump_image_bytes(self) -> bytes:
        try:
            exif_bytes = piexif.dump(self._ef)
        except piexif.InvalidImageDataError:
            if self._ef.get("thumbnail") == b"":
                # workaround https://github.com/hMatoba/Piexif/issues/30
                del self._ef["thumbnail"]
                if "1st" in self._ef:
                    del self._ef["1st"]
                exif_bytes = piexif.dump(self._ef)
            else:
                raise
        output = io.BytesIO()
        piexif.insert(exif_bytes, self._filename, output)
        return output.read()

    def write(self, filename=None):
        """Save exif data to file."""
        if filename is None:
            filename = self._filename

        try:
            exif_bytes = piexif.dump(self._ef)
        except piexif.InvalidImageDataError:
            if self._ef.get("thumbnail") == b"":
                # workaround https://github.com/hMatoba/Piexif/issues/30
                del self._ef["thumbnail"]
                if "1st" in self._ef:
                    del self._ef["1st"]
                exif_bytes = piexif.dump(self._ef)
            else:
                raise

        with open(self._filename, "rb") as fp:
            img = fp.read()

        piexif.insert(exif_bytes, img, filename)
