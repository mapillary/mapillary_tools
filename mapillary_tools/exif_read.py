import datetime
import abc
import typing as T
from pathlib import Path
import xml.etree.ElementTree as et

import exifread
from exifread.utils import Ratio


XMP_NAMESPACES = {
    "exif": "http://ns.adobe.com/exif/1.0/",
    "tiff": "http://ns.adobe.com/tiff/1.0/",
    "exifEX": "http://cipa.jp/exif/1.0/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "x": "adobe:ns:meta/",
}


def eval_frac(value: Ratio) -> float:
    return float(value.num) / float(value.den)


def gps_to_decimal(values: T.Tuple[Ratio, Ratio, Ratio]) -> T.Optional[float]:
    try:
        deg, min, sec, *_ = values
    except (TypeError, ValueError):
        return None
    if not isinstance(deg, Ratio):
        return None
    if not isinstance(min, Ratio):
        return None
    if not isinstance(sec, Ratio):
        return None
    try:
        degrees = eval_frac(deg)
        minutes = eval_frac(min)
        seconds = eval_frac(sec)
    except ZeroDivisionError:
        return None
    return degrees + minutes / 60 + seconds / 3600


def strptime_alternative_formats(
    dtstr: str, formats: T.Sequence[str]
) -> T.Optional[datetime.datetime]:
    for format in formats:
        try:
            return datetime.datetime.strptime(dtstr, format)
        except ValueError:
            continue
    return None


def parse_timestr(timestr: str) -> T.Optional[datetime.timedelta]:
    parts = timestr.strip().split(":")

    try:
        if len(parts) == 0:
            raise ValueError
        elif len(parts) == 1:
            h, m, s = int(parts[0]), 0, 0.0
        elif len(parts) == 2:
            h, m, s = int(parts[0]), int(parts[1]), 0.0
        else:
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    except ValueError:
        return None

    return datetime.timedelta(hours=h, minutes=m, seconds=s)


def make_valid_timezone_offset(delta: datetime.timedelta) -> datetime.timedelta:
    # otherwise: ValueError: offset must be a timedelta strictly between -timedelta(hours=24)
    # and timedelta(hours=24), not datetime.timedelta(days=1)
    h24 = datetime.timedelta(hours=24)
    if h24 <= delta:
        delta = delta % h24
    elif delta <= -h24:
        delta = delta % -h24
    return delta


_FIELD_TYPE = T.TypeVar("_FIELD_TYPE", int, float, str)


def parse_datetimestr(
    dtstr: str, subsec: T.Optional[str] = None, tz_offset: T.Optional[str] = None
) -> T.Optional[datetime.datetime]:
    """
    Convert dtstr "YYYY:mm:dd HH:MM:SS[.sss]" to a datetime object.
    It handles time "24:00:00" as "00:00:00" of the next day.
    subsec "123" will be parsed as seconds 0.123 i.e microseconds 123000 and added to the datetime object.
    """
    dtstr = dtstr.strip()
    date_and_time = dtstr.split(maxsplit=2)
    if len(date_and_time) < 2:
        return None
    date, time = date_and_time[:2]
    d = strptime_alternative_formats(date, ["%Y:%m:%d", "%Y-%m-%d"])
    if d is None:
        return None
    time_delta = parse_timestr(time)
    if time_delta is None:
        # unable to parse HH:MM:SS
        return None
    d = d + time_delta
    if subsec is not None:
        if len(subsec) < 6:
            subsec = subsec + ("0" * 6)
        microseconds = int(subsec[:6])
        # ValueError: microsecond must be in 0..999999
        microseconds = microseconds % int(1e6)
        # always overrides the microseconds
        d = d.replace(microsecond=microseconds)
    if tz_offset is not None:
        if tz_offset.startswith("+"):
            offset_delta = parse_timestr(tz_offset[1:])
        elif tz_offset.startswith("-"):
            offset_delta = parse_timestr(tz_offset[1:])
            if offset_delta is not None:
                offset_delta = -1 * offset_delta
        else:
            offset_delta = parse_timestr(tz_offset)
        if offset_delta is not None:
            offset_delta = make_valid_timezone_offset(offset_delta)
            tzinfo = datetime.timezone(offset_delta)
            d = d.replace(tzinfo=tzinfo)
    return d


class ExifReadABC(abc.ABC):
    @abc.abstractmethod
    def extract_altitude(self) -> T.Optional[float]:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_capture_time(self) -> T.Optional[datetime.datetime]:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_direction(self) -> T.Optional[float]:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_lon_lat(self) -> T.Optional[T.Tuple[float, float]]:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_make(self) -> T.Optional[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_model(self) -> T.Optional[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_width(self) -> T.Optional[int]:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_height(self) -> T.Optional[int]:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_orientation(self) -> int:
        raise NotImplementedError


class ExifReadFromXMP(ExifReadABC):
    def __init__(self, etree: et.ElementTree):
        self.etree = etree
        self.first_rdf_description = self.etree.find(
            ".//rdf:Description", namespaces=XMP_NAMESPACES
        )

    def extract_altitude(self) -> T.Optional[float]:
        if self.first_rdf_description is None:
            return None
        altitude = self._extract_alternative_attribute(["exif:GPSAltitude"])
        if altitude is None:
            return None
        try:
            return float(altitude)
        except ValueError:
            return None

    def _extract_exif_datetime(
        self, dt_tag: str, subsec_tag: str, offset_tag: str
    ) -> T.Optional[datetime.datetime]:
        dtstr = self._extract_alternative_attribute([dt_tag])
        if dtstr is None:
            return None
        subsec = self._extract_alternative_attribute([subsec_tag])
        # See https://github.com/mapillary/mapillary_tools/issues/388#issuecomment-860198046
        # and https://community.gopro.com/t5/Cameras/subsecond-timestamp-bug/m-p/1057505
        if subsec:
            subsec = subsec.replace(" ", "0")
        offset = self._extract_alternative_attribute([offset_tag])
        dt = parse_datetimestr(dtstr, subsec, offset)
        if dt is None:
            return None
        return dt

    def extract_exif_datetime(self) -> T.Optional[datetime.datetime]:
        dt = self._extract_exif_datetime(
            "exif:DateTimeOriginal",
            "exif:SubSecTimeOriginal",
            "exif:OffsetTimeOriginal",
        )
        if dt is not None:
            return dt

        dt = self._extract_exif_datetime(
            "exif:DateTimeDigitized",
            "exif:SubSecTimeDigitized",
            "exif:OffsetTimeDigitized",
        )
        if dt is not None:
            return dt

        return None

    def extract_gps_datetime(self) -> T.Optional[datetime.datetime]:
        """
        Extract timestamp from GPS field.
        """
        gpsdate = self._extract_alternative_attribute(["exif:GPSDateStamp"])
        if gpsdate is None:
            return None
        dt = strptime_alternative_formats(gpsdate, ["%Y:%m:%d"])
        if dt is None:
            return None
        gpstimestamp = self._extract_alternative_attribute(["exif:GPSTimeStamp"])
        if not gpstimestamp:
            return None
        try:
            h, m, s, *_ = gpstimestamp.split(":")
            hour = int(h)
            minute = int(m)
            second = float(s)
        except (ValueError, TypeError):
            return None
        dt = dt + datetime.timedelta(hours=hour, minutes=minute, seconds=second)
        # GPS timestamps are always GMT
        dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt

    def extract_capture_time(self) -> T.Optional[datetime.datetime]:
        if self.first_rdf_description is None:
            return None

        dt = self.extract_gps_datetime()
        if dt is not None:
            return dt

        dt = self.extract_exif_datetime()
        if dt is not None:
            return dt

        return None

    def extract_direction(self) -> T.Optional[float]:
        if self.first_rdf_description is None:
            return None
        direction = self._extract_alternative_attribute(
            ["exif:GPSImgDirection", "exif:GPSTrack"]
        )
        if direction is None:
            return None
        try:
            return float(direction)
        except ValueError:
            return None

    def extract_lon_lat(self) -> T.Optional[T.Tuple[float, float]]:
        if self.first_rdf_description is None:
            return None
        lat_str = self._extract_alternative_attribute(["exif:GPSLatitude"])
        lon_str = self._extract_alternative_attribute(["exif:GPSLongitude"])
        if lat_str is not None and lon_str is not None:
            lon = float(lon_str)
            if lon is None:
                return None
            ref = self._extract_alternative_attribute(["exif:GPSLongitudeRef"])
            if ref and ref.upper() == "W":
                lon = -1 * lon

            lat = float(lat_str)
            if lat is None:
                return None
            ref = self._extract_alternative_attribute(["exif:GPSLatitudeRef"])
            if ref and ref.upper() == "S":
                lat = -1 * lat

            return lon, lat

        return None

    def extract_make(self) -> T.Optional[str]:
        if self.first_rdf_description is None:
            return None
        return self._extract_alternative_attribute(["exifEX:LensMake", "tiff:Make"])

    def extract_model(self) -> T.Optional[str]:
        if self.first_rdf_description is None:
            return None
        return self._extract_alternative_attribute(["exifEX:LensModel", "tiff:Model"])

    def extract_width(self) -> T.Optional[int]:
        if self.first_rdf_description is None:
            return None
        x = self._extract_alternative_attribute(["exif:PixelXDimension"])
        if x is None:
            return None
        try:
            return int(x)
        except ValueError:
            return None

    def extract_height(self) -> T.Optional[int]:
        if self.first_rdf_description is None:
            return None
        y = self._extract_alternative_attribute(["exif:PixelYDimension"])
        if y is None:
            return None
        try:
            return int(y)
        except ValueError:
            return None

    def extract_orientation(self) -> int:
        if self.first_rdf_description is None:
            return 1
        orientation = self._extract_alternative_attribute(["tiff:Orientation"])
        if orientation is None:
            return 1
        try:
            return int(orientation)
        except ValueError:
            return 1

    def _extract_alternative_attribute(
        self,
        fields: T.Sequence[str],
    ) -> T.Optional[str]:
        """
        Extract a value for a list of ordered fields.
        Return the value of the first existed field in the list
        """
        if self.first_rdf_description is None:
            return None
        for field in fields:
            ns, attr = field.split(":")
            value = self.first_rdf_description.get(
                "{" + XMP_NAMESPACES[ns] + "}" + attr
            )
            if value is not None:
                return value
        return None


class ExifReadFromEXIF(ExifReadABC):
    """
    EXIF class for reading exif from an image
    """

    def __init__(
        self, path_or_stream: T.Union[Path, T.BinaryIO], details: bool = False
    ) -> None:
        """
        Initialize EXIF object with FILE as filename or fileobj
        """
        if isinstance(path_or_stream, Path):
            with path_or_stream.open("rb") as fp:
                self.tags = exifread.process_file(fp, details=details, debug=True)
        else:
            self.tags = exifread.process_file(
                path_or_stream, details=details, debug=True
            )

    def extract_xmp(self) -> T.Optional[ExifReadFromXMP]:
        application_notes = self._extract_application_notes()
        if application_notes is None:
            return None
        return ExifReadFromXMP(application_notes)

    def extract_altitude(self) -> T.Optional[float]:
        """
        Extract altitude
        """
        altitude = self._extract_alternative_fields(["GPS GPSAltitude"], float)
        if altitude is None:
            return None
        ref = self._extract_alternative_fields(["GPS GPSAltitudeRef"], int)
        if ref is None:
            ref = 0
        altitude_ref = {0: 1, 1: -1}
        return altitude * altitude_ref.get(ref, 1)

    def extract_gps_datetime(self) -> T.Optional[datetime.datetime]:
        """
        Extract timestamp from GPS field.
        """
        gpsdate = self._extract_alternative_fields(["GPS GPSDate"], str)
        if gpsdate is None:
            return None
        dt = strptime_alternative_formats(gpsdate, ["%Y:%m:%d"])
        if dt is None:
            return None
        gpstimestamp = self.tags.get("GPS GPSTimeStamp")
        if not gpstimestamp:
            return None
        try:
            h, m, s, *_ = gpstimestamp.values
        except (ValueError, TypeError):
            return None
        if not isinstance(h, Ratio):
            return None
        if not isinstance(m, Ratio):
            return None
        if not isinstance(s, Ratio):
            return None
        hour = int(eval_frac(h))
        minute = int(eval_frac(m))
        second = float(eval_frac(s))
        dt = dt + datetime.timedelta(hours=hour, minutes=minute, seconds=second)
        # GPS timestamps are always GMT
        dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt

    def _extract_exif_datetime(
        self, dt_tag: str, subsec_tag: str, offset_tag: str
    ) -> T.Optional[datetime.datetime]:
        dtstr = self._extract_alternative_fields([dt_tag], field_type=str)
        if dtstr is None:
            return None
        subsec = self._extract_alternative_fields([subsec_tag], field_type=str)
        # See https://github.com/mapillary/mapillary_tools/issues/388#issuecomment-860198046
        # and https://community.gopro.com/t5/Cameras/subsecond-timestamp-bug/m-p/1057505
        if subsec:
            subsec = subsec.replace(" ", "0")
        offset = self._extract_alternative_fields([offset_tag], field_type=str)
        dt = parse_datetimestr(dtstr, subsec, offset)
        if dt is None:
            return None
        return dt

    def extract_exif_datetime(self) -> T.Optional[datetime.datetime]:
        # EXIF DateTimeOriginal: 0x9003 (date/time when original image was taken)
        # EXIF SubSecTimeOriginal: 0x9291 (fractional seconds for DateTimeOriginal)
        # EXIF OffsetTimeOriginal: 0x9011 (time zone for DateTimeOriginal)
        dt = self._extract_exif_datetime(
            "EXIF DateTimeOriginal",
            "EXIF SubSecTimeOriginal",
            "EXIF OffsetTimeOriginal",
        )
        if dt is not None:
            return dt

        # EXIF DateTimeDigitized: 0x9004 CreateDate in ExifTool (called DateTimeDigitized by the EXIF spec.)
        # EXIF SubSecTimeDigitized: 0x9292 (fractional seconds for CreateDate)
        # EXIF OffsetTimeDigitized: 0x9012 (time zone for CreateDate)
        dt = self._extract_exif_datetime(
            "EXIF DateTimeDigitized",
            "EXIF SubSecTimeDigitized",
            "EXIF OffsetTimeDigitized",
        )
        if dt is not None:
            return dt

        # Image DateTime: 0x0132 ModifyDate in ExifTool (called DateTime by the EXIF spec.)
        # EXIF SubSecTime: 0x9290 (fractional seconds for ModifyDate)
        # EXIF OffsetTime: 0x9010 (time zone for ModifyDate)
        dt = self._extract_exif_datetime(
            "Image DateTime", "EXIF SubSecTime", "EXIF OffsetTime"
        )
        if dt is not None:
            return dt

        return None

    def extract_capture_time(self) -> T.Optional[datetime.datetime]:
        """
        Extract capture time from EXIF DateTime tags
        """
        # Prefer GPS datetime over EXIF timestamp
        # NOTE: GPS datetime precision is usually 1 second, but this case is handled by the subsecond interpolation
        try:
            gps_dt = self.extract_gps_datetime()
        except (ValueError, TypeError, ZeroDivisionError):
            gps_dt = None
        if gps_dt is not None:
            return gps_dt

        dt = self.extract_exif_datetime()
        if dt is not None:
            return dt

        return None

    def extract_direction(self) -> T.Optional[float]:
        """
        Extract image direction (i.e. compass, heading, bearing)
        """
        fields = [
            "GPS GPSImgDirection",
            "GPS GPSTrack",
        ]
        direction = self._extract_alternative_fields(fields, float)
        if direction is not None:
            if direction > 360:
                # fix negative value wrongly parsed in exifread
                # -360 degree -> 4294966935 when converting from hex
                bearing1 = bin(int(direction))[2:]
                bearing2 = "".join([str(int(int(a) == 0)) for a in bearing1])
                direction = -float(int(bearing2, 2))
            direction %= 360

        return direction

    def extract_lon_lat(self) -> T.Optional[T.Tuple[float, float]]:
        lat_tag = self.tags.get("GPS GPSLatitude")
        lon_tag = self.tags.get("GPS GPSLongitude")
        if lat_tag and lon_tag:
            lon = gps_to_decimal(lon_tag.values)
            if lon is None:
                return None
            ref = self._extract_alternative_fields(["GPS GPSLongitudeRef"], str)
            if ref and ref.upper() == "W":
                lon = -1 * lon

            lat = gps_to_decimal(lat_tag.values)
            if lat is None:
                return None
            ref = self._extract_alternative_fields(["GPS GPSLatitudeRef"], str)
            if ref and ref.upper() == "S":
                lat = -1 * lat

            return lon, lat

        return None

    def extract_make(self) -> T.Optional[str]:
        """
        Extract camera make
        """
        return self._extract_alternative_fields(["EXIF LensMake", "Image Make"], str)

    def extract_model(self) -> T.Optional[str]:
        """
        Extract camera model
        """
        return self._extract_alternative_fields(["EXIF LensModel", "Image Model"], str)

    def extract_width(self) -> T.Optional[int]:
        """
        Extract image width in pixels
        """
        return self._extract_alternative_fields(
            ["Image ImageWidth", "EXIF ExifImageWidth"], int
        )

    def extract_height(self) -> T.Optional[int]:
        """
        Extract image height in pixels
        """
        return self._extract_alternative_fields(
            ["Image ImageLength", "EXIF ExifImageLength"], int
        )

    def extract_orientation(self) -> int:
        """
        Extract image orientation
        """
        orientation = self._extract_alternative_fields(["Image Orientation"], int)
        if orientation is None:
            orientation = 1
        if orientation not in range(1, 9):
            return 1
        return orientation

    def _extract_alternative_fields(
        self,
        fields: T.Sequence[str],
        field_type: T.Type[_FIELD_TYPE],
    ) -> T.Optional[_FIELD_TYPE]:
        """
        Extract a value for a list of ordered fields.
        Return the value of the first existed field in the list
        """
        for field in fields:
            tag = self.tags.get(field)
            if tag is None:
                continue
            values = tag.values
            if field_type is float:
                if values and isinstance(values[0], Ratio):
                    try:
                        return T.cast(_FIELD_TYPE, eval_frac(values[0]))
                    except ZeroDivisionError:
                        pass
            elif field_type is str:
                return T.cast(_FIELD_TYPE, str(values))
            elif field_type is int:
                if values:
                    try:
                        return T.cast(_FIELD_TYPE, int(values[0]))
                    except (ValueError, TypeError):
                        pass
            else:
                raise ValueError(f"Invalid field type {field_type}")
        return None

    def _extract_application_notes(self) -> T.Optional[et.ElementTree]:
        xmp = self.tags.get("Image ApplicationNotes")
        if xmp is None:
            return None
        try:
            e = et.fromstring(str(xmp))
        except et.ParseError:
            return None
        return et.ElementTree(e)


class ExifRead(ExifReadFromEXIF):
    def __init__(
        self, path_or_stream: T.Union[Path, T.BinaryIO], details: bool = False
    ) -> None:
        super().__init__(path_or_stream, details)
        self._xmp = self.extract_xmp()

    def extract_altitude(self) -> T.Optional[float]:
        val = super().extract_altitude()
        if val is not None:
            return val
        if self._xmp is None:
            return None
        val = self._xmp.extract_altitude()
        if val is not None:
            return val
        return None

    def extract_capture_time(self) -> T.Optional[datetime.datetime]:
        val = super().extract_capture_time()
        if val is not None:
            return val
        if self._xmp is None:
            return None
        val = self._xmp.extract_capture_time()
        if val is not None:
            return val
        return None

    def extract_direction(self) -> T.Optional[float]:
        val = super().extract_direction()
        if val is not None:
            return val
        if self._xmp is None:
            return None
        val = self._xmp.extract_direction()
        if val is not None:
            return val
        return None

    def extract_lon_lat(self) -> T.Optional[T.Tuple[float, float]]:
        val = super().extract_lon_lat()
        if val is not None:
            return val
        if self._xmp is None:
            return None
        val = self._xmp.extract_lon_lat()
        if val is not None:
            return val
        return None

    def extract_make(self) -> T.Optional[str]:
        val = super().extract_make()
        if val is not None:
            return val
        if self._xmp is None:
            return None
        val = self._xmp.extract_make()
        if val is not None:
            return val
        return None

    def extract_model(self) -> T.Optional[str]:
        val = super().extract_model()
        if val is not None:
            return val
        if self._xmp is None:
            return None
        val = self._xmp.extract_model()
        if val is not None:
            return val
        return None

    def extract_width(self) -> T.Optional[int]:
        val = super().extract_width()
        if val is not None:
            return val
        if self._xmp is None:
            return None
        val = self._xmp.extract_width()
        if val is not None:
            return val
        return None

    def extract_height(self) -> T.Optional[int]:
        val = super().extract_height()
        if val is not None:
            return val
        if self._xmp is None:
            return None
        val = self._xmp.extract_height()
        if val is not None:
            return val
        return None
