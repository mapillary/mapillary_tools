import sys
from typing import List, Optional, Tuple, Type, Union, Any
import datetime
import os

import exifread
from exifread.utils import Ratio

from .geo import normalize_bearing


def eval_frac(value: Ratio) -> float:
    return float(value.num) / float(value.den)


def format_time(time_string: str) -> Tuple[datetime.datetime, bool]:
    """
    Format time string with invalid time elements in hours/minutes/seconds
    Format for the timestring needs to be "%Y_%m_%d_%H_%M_%S"

    e.g. 2014_03_31_24_10_11 => 2014_04_01_00_10_11
    """
    subseconds = False
    data = time_string.split("_")
    hours, minutes, seconds = int(data[3]), int(data[4]), int(data[5])
    date = datetime.datetime.strptime("_".join(data[:3]), "%Y_%m_%d")
    subsec = 0.0
    if len(data) == 7:
        if float(data[6]) != 0:
            subsec = float(data[6]) / 10 ** len(data[6])
            subseconds = True
    date_time = date + datetime.timedelta(
        hours=hours, minutes=minutes, seconds=seconds + subsec
    )
    return date_time, subseconds


def gps_to_decimal(values: List[Ratio], reference: str) -> Optional[float]:
    sign = 1 if reference in "NE" else -1
    deg, min, sec = values
    try:
        degrees = eval_frac(deg)
        minutes = eval_frac(min)
        seconds = eval_frac(sec)
    except ZeroDivisionError:
        return None
    return sign * (degrees + minutes / 60 + seconds / 3600)


def exif_datetime_fields() -> List[List[str]]:
    """
    Date time fields in EXIF
    """
    return [
        [
            "EXIF DateTimeOriginal",
            "Image DateTimeOriginal",
            "EXIF DateTimeDigitized",
            "Image DateTimeDigitized",
            "EXIF DateTime",
            "Image DateTime",
            "GPS GPSDate",
            "EXIF GPS GPSDate",
            "EXIF DateTimeModified",
        ]
    ]


def exif_gps_date_fields() -> List[List[str]]:
    """
    Date fields in EXIF GPS
    """
    return [["GPS GPSDate", "EXIF GPS GPSDate"]]


class ExifRead:
    """
    EXIF class for reading exif from an image
    """

    def __init__(self, filename: str, details: bool = False) -> None:
        """
        Initialize EXIF object with FILE as filename or fileobj
        """
        self.filename = filename
        if isinstance(filename, str):
            with open(filename, "rb") as fp:
                self.tags = exifread.process_file(fp, details=details, debug=True)
        else:
            self.tags = exifread.process_file(filename, details=details, debug=True)

    def _extract_alternative_fields(
        self,
        fields: List[str],
        default: Optional[Union[str, int, float]] = None,
        field_type: Union[Type[float], Type[str], Type[int]] = float,
    ) -> Tuple[Any, Optional[str]]:
        """
        Extract a value for a list of ordered fields.
        Return the value of the first existed field in the list
        """
        for field in fields:
            if field in self.tags:
                if field_type is float:
                    try:
                        return eval_frac(self.tags[field].values[0]), field
                    except ZeroDivisionError:
                        pass
                elif field_type is str:
                    return str(self.tags[field].values), field
                elif field_type is int:
                    return int(self.tags[field].values[0]), field
                else:
                    raise ValueError(f"Invalid field type {field_type}")
        return default, None

    def extract_altitude(self) -> Optional[float]:
        """
        Extract altitude
        """
        fields: List[str] = ["GPS GPSAltitude", "EXIF GPS GPSAltitude"]
        altitude, _ = self._extract_alternative_fields(
            fields, default=None, field_type=float
        )
        if altitude is None:
            return None
        fields = ["GPS GPSAltitudeRef", "EXIF GPS GPSAltitudeRef"]
        ref, _ = self._extract_alternative_fields(fields, default=0, field_type=int)
        altitude_ref = {0: 1, 1: -1}
        return altitude * altitude_ref.get(ref, 1)

    def extract_capture_time(self) -> Optional[datetime.datetime]:
        """
        Extract capture time from EXIF
        return a datetime object
        TODO: handle GPS DateTime
        """
        time_string = exif_datetime_fields()[0]
        capture_time, time_field = self._extract_alternative_fields(
            time_string, default=None, field_type=str
        )
        if time_field in exif_gps_date_fields()[0]:
            return self.extract_gps_time()

        if capture_time is None:
            # try interpret the filename
            basename, _ = os.path.splitext(os.path.basename(self.filename))
            try:
                return datetime.datetime.strptime(
                    basename + "000", "%Y_%m_%d_%H_%M_%S_%f"
                )
            except ValueError:
                return None
        else:
            capture_time = capture_time.replace(" ", "_")
            capture_time = capture_time.replace(":", "_")
            capture_time = capture_time.replace(".", "_")
            capture_time = capture_time.replace("-", "_")
            capture_time = capture_time.replace(",", "_")
            capture_time = "_".join(
                [ts for ts in capture_time.split("_") if ts.isdigit()]
            )
            capture_time_obj, has_subseconds = format_time(capture_time)
            if not has_subseconds:
                sub_sec = self._extract_subsec()
                # Fix spaces in subsec in gopro
                # See https://github.com/mapillary/mapillary_tools/issues/388#issuecomment-860198046
                # and https://community.gopro.com/t5/Cameras/subsecond-timestamp-bug/m-p/1057505
                if sub_sec.startswith(" "):
                    make = self.extract_make()
                    if make is not None and make.lower() == "gopro":
                        sub_sec = sub_sec.replace(" ", "0")
                capture_time_obj = capture_time_obj + datetime.timedelta(
                    seconds=float("0." + sub_sec)
                )
            return capture_time_obj

    def extract_direction(self) -> Optional[float]:
        """
        Extract image direction (i.e. compass, heading, bearing)
        """
        fields = [
            "GPS GPSImgDirection",
            "EXIF GPS GPSImgDirection",
            "GPS GPSTrack",
            "EXIF GPS GPSTrack",
        ]
        direction, _ = self._extract_alternative_fields(
            fields, default=None, field_type=float
        )

        if direction is not None:
            direction = normalize_bearing(direction, check_hex=True)

        return direction

    def extract_gps_time(self) -> Optional[datetime.datetime]:
        """
        Extract timestamp from GPS field.
        """
        gps_date_field = "GPS GPSDate"
        gps_time_field = "GPS GPSTimeStamp"
        if gps_date_field in self.tags and gps_time_field in self.tags:
            date = str(self.tags[gps_date_field].values).split(":")
            if int(date[0]) == 0 or int(date[1]) == 0 or int(date[2]) == 0:
                return None
            t = self.tags[gps_time_field]
            gps_time = datetime.datetime(
                year=int(date[0]),
                month=int(date[1]),
                day=int(date[2]),
                hour=int(eval_frac(t.values[0])),
                minute=int(eval_frac(t.values[1])),
                second=int(eval_frac(t.values[2])),
            )
            microseconds = datetime.timedelta(
                microseconds=int((eval_frac(t.values[2]) % 1) * 1e6)
            )
            gps_time += microseconds
            return gps_time
        else:
            return None

    def extract_lon_lat(self) -> Tuple[Optional[float], Optional[float]]:
        lat_tag = self.tags.get("GPS GPSLatitude")
        lon_tag = self.tags.get("GPS GPSLongitude")
        if lat_tag and lon_tag:
            lat_ref_tag = self.tags.get("GPS GPSLatitudeRef")
            lat = gps_to_decimal(
                lat_tag.values, lat_ref_tag.values if lat_ref_tag else "N"
            )
            lon_ref_tag = self.tags.get("GPS GPSLongitudeRef")
            lon = gps_to_decimal(
                lon_tag.values, lon_ref_tag.values if lon_ref_tag else "E"
            )
            if lon is not None and lat is not None:
                return lon, lat

        # repeat above
        lat_tag = self.tags.get("EXIF GPS GPSLatitude")
        lon_tag = self.tags.get("EXIF GPS GPSLongitude")
        if lat_tag and lon_tag:
            lat_ref_tag = self.tags.get("EXIF GPS GPSLatitudeRef")
            lat = gps_to_decimal(
                lat_tag.values, lat_ref_tag.values if lat_ref_tag else "N"
            )
            lon_ref_tag = self.tags.get("EXIF GPS GPSLongitudeRef")
            lon = gps_to_decimal(
                lon_tag.values, lon_ref_tag.values if lon_ref_tag else "E"
            )
            if lon is not None and lat is not None:
                return lon, lat

        return None, None

    def extract_make(self) -> Optional[str]:
        """
        Extract camera make
        """
        fields = ["EXIF LensMake", "Image Make"]
        make, _ = self._extract_alternative_fields(fields, default=None, field_type=str)
        return make

    def extract_model(self) -> Optional[str]:
        """
        Extract camera model
        """
        fields = ["EXIF LensModel", "Image Model"]
        model, _ = self._extract_alternative_fields(
            fields, default=None, field_type=str
        )
        return model

    def extract_orientation(self) -> int:
        """
        Extract image orientation
        """
        fields = ["Image Orientation"]
        orientation, _ = self._extract_alternative_fields(
            fields, default=1, field_type=int
        )
        if orientation not in range(1, 9):
            return 1
        return orientation

    def _extract_subsec(self) -> str:
        """
        Extract microseconds
        """
        fields = [
            "Image SubSecTimeOriginal",
            "EXIF SubSecTimeOriginal",
            "Image SubSecTimeDigitized",
            "EXIF SubSecTimeDigitized",
            "Image SubSecTime",
            "EXIF SubSecTime",
        ]
        sub_sec, _ = self._extract_alternative_fields(
            fields, default="", field_type=str
        )
        return sub_sec


if __name__ == "__main__":
    import pprint

    for filename in sys.argv[1:]:
        exif = ExifRead(filename, details=True)
        pprint.pprint(
            {
                "capture_time": exif.extract_capture_time(),
                "gps_time": exif.extract_gps_time(),
                "direction": exif.extract_direction(),
                "model": exif.extract_model(),
                "make": exif.extract_make(),
                "lon_lat": exif.extract_lon_lat(),
                "altitude": exif.extract_altitude(),
            }
        )
