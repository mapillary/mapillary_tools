from typing import List, Optional, Tuple, Type, Union, Any
import datetime
import json
import os
import logging

import exifread

from .geo import normalize_bearing
from exifread.utils import Ratio


LOG = logging.getLogger()


def eval_frac(value: Ratio) -> float:
    if value.den == 0:
        return -1.0
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


def gps_to_decimal(values: List[Ratio], reference: str) -> float:
    sign = 1 if reference in "NE" else -1
    degrees = eval_frac(values[0])
    minutes = eval_frac(values[1])
    seconds = eval_frac(values[2])
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
                self.tags = exifread.process_file(fp, details=details)
        else:
            self.tags = exifread.process_file(filename, details=details)

    def _extract_alternative_fields(
        self,
        fields: List[str],
        default: Optional[Union[str, int]] = None,
        field_type: Union[Type[float], Type[str], Type[int]] = float,
    ) -> Union[Tuple[Any, Any]]:
        """
        Extract a value for a list of ordered fields.
        Return the value of the first existed field in the list
        """
        for field in fields:
            if field in self.tags:
                if field_type is float:
                    return eval_frac(self.tags[field].values[0]), field
                elif field_type is str:
                    return str(self.tags[field].values), field
                elif field_type is int:
                    return int(self.tags[field].values[0]), field
                else:
                    return None, field
        return default, None

    def extract_image_history(self) -> str:
        field = ["Image Tag 0x9213"]
        user_comment, _ = self._extract_alternative_fields(field, "{}", str)
        return user_comment

    def extract_altitude(self) -> float:
        """
        Extract altitude
        """
        altitude_ref = {0: 1, 1: -1}
        fields: List[str] = ["GPS GPSAltitude", "EXIF GPS GPSAltitude"]
        refs: List[str] = ["GPS GPSAltitudeRef", "EXIF GPS GPSAltitudeRef"]
        altitude, _ = self._extract_alternative_fields(fields, 0, float)
        ref = (
            0
            if not any([True for x in refs if x in self.tags])
            else [self.tags[x].values for x in refs if x in self.tags][0][0]
        )
        return altitude * altitude_ref[ref]

    def extract_capture_time(self) -> Optional[datetime.datetime]:
        """
        Extract capture time from EXIF
        return a datetime object
        TODO: handle GPS DateTime
        """
        time_string = exif_datetime_fields()[0]
        capture_time, time_field = self._extract_alternative_fields(
            time_string, None, str
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
            capture_time_obj, subseconds = format_time(capture_time)
            sub_sec = "0"
            if not subseconds:
                sub_sec = self.extract_subsec()
                if isinstance(sub_sec, str):
                    sub_sec = sub_sec.strip()
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
        direction, _ = self._extract_alternative_fields(fields)

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

    def extract_image_description(self) -> Optional[str]:
        description, _ = self._extract_alternative_fields(
            ["Image ImageDescription"], None, str
        )
        return description

    def extract_lon_lat(self) -> Tuple[Optional[float], Optional[float]]:
        if "GPS GPSLatitude" in self.tags and "GPS GPSLatitude" in self.tags:
            lat: Optional[float] = gps_to_decimal(
                self.tags["GPS GPSLatitude"].values,
                self.tags["GPS GPSLatitudeRef"].values,
            )
            lon: Optional[float] = gps_to_decimal(
                self.tags["GPS GPSLongitude"].values,
                self.tags["GPS GPSLongitudeRef"].values,
            )
        elif (
            "EXIF GPS GPSLatitude" in self.tags and "EXIF GPS GPSLatitude" in self.tags
        ):
            lat = gps_to_decimal(
                self.tags["EXIF GPS GPSLatitude"].values,
                self.tags["EXIF GPS GPSLatitudeRef"].values,
            )
            lon = gps_to_decimal(
                self.tags["EXIF GPS GPSLongitude"].values,
                self.tags["EXIF GPS GPSLongitudeRef"].values,
            )
        else:
            lon, lat = None, None
        return lon, lat

    def extract_make(self) -> str:
        """
        Extract camera make
        """
        fields = ["EXIF LensMake", "Image Make"]
        make, _ = self._extract_alternative_fields(
            fields, default="none", field_type=str
        )
        return make

    def extract_model(self) -> str:
        """
        Extract camera model
        """
        fields = ["EXIF LensModel", "Image Model"]
        model, _ = self._extract_alternative_fields(
            fields, default="none", field_type=str
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

    def extract_subsec(self) -> str:
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

    def mapillary_tag_exists(self):
        """
        Check existence of required Mapillary tags
        """
        description = self.extract_image_description()
        if description is None:
            return False

        try:
            description_values = json.loads(description)
        except json.JSONDecodeError:
            LOG.warning(f"Error JSON decoding ImageDescription: {description}")
            return False

        for requirement in [
            "MAPCaptureTime",
            "MAPLatitude",
            "MAPLongitude",
            "MAPSequenceUUID",
            "MAPSettingsUserKey",
        ]:
            val = description_values.get(requirement)
            if val is None:
                return False
            elif isinstance(val, str):
                if not val.strip():
                    return False
        return True
