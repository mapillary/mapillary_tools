import abc
import datetime
import logging
import re
import typing as T
import xml.etree.ElementTree as et
from fractions import Fraction
from pathlib import Path

import exifread
from exifread.utils import Ratio


XMP_NAMESPACES = {
    "exif": "http://ns.adobe.com/exif/1.0/",
    "tiff": "http://ns.adobe.com/tiff/1.0/",
    "exifEX": "http://cipa.jp/exif/1.0/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "x": "adobe:ns:meta/",
    "GPano": "http://ns.google.com/photos/1.0/panorama/",
}
# https://github.com/ianare/exif-py/issues/167
EXIFREAD_LOG = logging.getLogger("exifread")
EXIFREAD_LOG.setLevel(logging.ERROR)
SIGN_BY_DIRECTION = {None: 1, "N": 1, "S": -1, "E": 1, "W": -1}
ADOBE_FORMAT_REGEX = re.compile(r"(\d+),(\d{1,3}\.?\d*)([NSWE])")


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


def _parse_coord_numeric(coord: str, ref: T.Optional[str]) -> T.Optional[float]:
    try:
        return float(coord) * SIGN_BY_DIRECTION[ref]
    except (ValueError, KeyError):
        return None


def _parse_coord_adobe(coord: str) -> T.Optional[float]:
    """
    Parse Adobe coordinate format: <degrees,fractionalminutes[NSEW]>
    """
    matches = ADOBE_FORMAT_REGEX.match(coord)
    if matches:
        deg = Ratio(int(matches.group(1)), 1)
        min_frac = Fraction.from_float(float(matches.group(2)))
        min = Ratio(min_frac.numerator, min_frac.denominator)
        sec = Ratio(0, 1)
        converted = gps_to_decimal((deg, min, sec))
        if converted is not None:
            return converted * SIGN_BY_DIRECTION[matches.group(3)]
    return None


def _parse_coord(coord: T.Optional[str], ref: T.Optional[str]) -> T.Optional[float]:
    if coord is None:
        return None
    parsed = _parse_coord_numeric(coord, ref)
    if parsed is None:
        parsed = _parse_coord_adobe(coord)
    return parsed


def _parse_iso(dtstr: str) -> T.Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromisoformat(dtstr)
    except ValueError:
        # fromisoformat does not support trailing Z
        return strptime_alternative_formats(
            dtstr, ["%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"]
        )


def strptime_alternative_formats(
    dtstr: str, formats: T.Sequence[str]
) -> T.Optional[datetime.datetime]:
    for format in formats:
        if format == "ISO":
            dt = _parse_iso(dtstr)
            if dt is not None:
                return dt
        else:
            try:
                return datetime.datetime.strptime(dtstr, format)
            except ValueError:
                pass
    return None


def parse_timestr_as_timedelta(timestr: str) -> T.Optional[datetime.timedelta]:
    timestr = timestr.strip()
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


def parse_time_ratios_as_timedelta(
    time_tuple: T.Sequence[Ratio],
) -> T.Optional[datetime.timedelta]:
    try:
        hours, minutes, seconds, *_ = time_tuple
    except (ValueError, TypeError):
        return None
    if not isinstance(hours, Ratio):
        return None
    if not isinstance(minutes, Ratio):
        return None
    if not isinstance(seconds, Ratio):
        return None
    try:
        h: int = int(eval_frac(hours))
        m: int = int(eval_frac(minutes))
        s: float = eval_frac(seconds)
    except (ValueError, ZeroDivisionError):
        return None
    return datetime.timedelta(hours=h, minutes=m, seconds=s)


def parse_gps_datetime(
    dtstr: str,
    default_tz: T.Optional[datetime.timezone] = datetime.timezone.utc,
) -> T.Optional[datetime.datetime]:
    dtstr = dtstr.strip()

    dt = strptime_alternative_formats(dtstr, ["ISO"])
    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz)
        return dt

    date_and_time = dtstr.split(maxsplit=2)
    if len(date_and_time) < 2:
        return None
    datestr, timestr, *_ = date_and_time
    return parse_gps_datetime_separately(datestr, timestr, default_tz=default_tz)


def parse_gps_datetime_separately(
    datestr: str,
    timestr: str,
    default_tz: T.Optional[datetime.timezone] = datetime.timezone.utc,
) -> T.Optional[datetime.datetime]:
    """
    Parse GPSDateStamp and GPSTimeStamp and return the corresponding datetime object in GMT.

    Valid examples:
    - "2021:08:02" "07:57:06"
    - "2022:06:10" "17:35:52.269367"
    - "2022:06:10" "17:35:52.269367Z"
    """
    datestr = datestr.strip()
    dt = strptime_alternative_formats(datestr, ["%Y:%m:%d", "%Y-%m-%d"])
    if dt is None:
        return None

    # split the time part and timezone part
    # examples: 12:22:00.123000+01:00
    #           12:22:00.123000Z
    #           12:22:00
    timestr = timestr.strip()
    if timestr.endswith("Z"):
        timepartstr = timestr[:-1]
        tzinfo = datetime.timezone.utc
    else:
        # find the first + or -
        idx = timestr.find("+")
        if idx < 0:
            idx = timestr.find("-")
        # if found, then parse the offset
        if 0 <= idx:
            timepartstr = timestr[:idx]
            offset_delta = parse_timestr_as_timedelta(timestr[idx + 1 :])
            if offset_delta is not None:
                if timestr[idx] == "-":
                    offset_delta = -offset_delta
                tzinfo = datetime.timezone(offset_delta)
            else:
                tzinfo = None
        else:
            timepartstr = timestr
            tzinfo = None

    delta = parse_timestr_as_timedelta(timepartstr)
    if delta is None:
        return None
    dt = dt + delta

    if tzinfo is None:
        tzinfo = default_tz

    dt = dt.replace(tzinfo=tzinfo)

    return dt


def parse_datetimestr_with_subsec_and_offset(
    dtstr: str, subsec: T.Optional[str] = None, tz_offset: T.Optional[str] = None
) -> T.Optional[datetime.datetime]:
    """
    Convert dtstr "YYYY:mm:dd HH:MM:SS[.sss]" to a datetime object.
    It handles time "24:00:00" as "00:00:00" of the next day.
    Subsec "123" will be parsed as seconds 0.123 i.e microseconds 123000 and added to the datetime object.
    """
    # handle dtstr
    dtstr = dtstr.strip()

    # example dtstr: <exif:DateTimeOriginal>2021-07-15T15:37:30+10:00</exif:DateTimeOriginal>
    # example dtstr: 'EXIF DateTimeOriginal': (0x9003) ASCII=2021:07:15 15:37:30 @ 1278
    dt = parse_gps_datetime(dtstr, default_tz=None)
    if dt is None:
        return None

    # handle subsec
    if subsec is not None:
        subsec = subsec.strip()
        if len(subsec) < 6:
            subsec = subsec + ("0" * 6)
        microseconds = int(subsec[:6])
        # ValueError: microsecond must be in 0..999999
        microseconds = microseconds % int(1e6)
        # always overrides the microseconds
        dt = dt.replace(microsecond=microseconds)

    # handle tz_offset
    if tz_offset is not None:
        tz_offset = tz_offset.strip()
        if tz_offset.startswith("+"):
            offset_delta = parse_timestr_as_timedelta(tz_offset[1:])
        elif tz_offset.startswith("-"):
            offset_delta = parse_timestr_as_timedelta(tz_offset[1:])
            if offset_delta is not None:
                offset_delta = -1 * offset_delta
        else:
            offset_delta = parse_timestr_as_timedelta(tz_offset)
        if offset_delta is not None:
            offset_delta = make_valid_timezone_offset(offset_delta)
            tzinfo = datetime.timezone(offset_delta)
            dt = dt.replace(tzinfo=tzinfo)

    return dt


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
        self._tags_or_attrs: T.Dict[str, str] = {}
        for description in self.etree.iterfind(
            ".//rdf:Description", namespaces=XMP_NAMESPACES
        ):
            for k, v in description.items():
                self._tags_or_attrs[k] = v
            for child in description:
                if child.text is not None:
                    self._tags_or_attrs[child.tag] = child.text

    def extract_altitude(self) -> T.Optional[float]:
        return self._extract_alternative_fields(["exif:GPSAltitude"], float)

    def _extract_exif_datetime(
        self, dt_tag: str, subsec_tag: str, offset_tag: str
    ) -> T.Optional[datetime.datetime]:
        dtstr = self._extract_alternative_fields([dt_tag], str)
        if dtstr is None:
            return None
        subsec = self._extract_alternative_fields([subsec_tag], str)
        # See https://github.com/mapillary/mapillary_tools/issues/388#issuecomment-860198046
        # and https://community.gopro.com/t5/Cameras/subsecond-timestamp-bug/m-p/1057505
        if subsec:
            subsec = subsec.replace(" ", "0")
        offset = self._extract_alternative_fields([offset_tag], str)
        dt = parse_datetimestr_with_subsec_and_offset(dtstr, subsec, offset)
        if dt is None:
            return None
        return dt

    def extract_exif_datetime(self) -> T.Optional[datetime.datetime]:
        dt = self._extract_exif_datetime(
            "exif:DateTimeOriginal",
            "exif:SubsecTimeOriginal",
            "exif:OffsetTimeOriginal",
        )
        if dt is not None:
            return dt

        dt = self._extract_exif_datetime(
            "exif:DateTimeDigitized",
            "exif:SubsecTimeDigitized",
            "exif:OffsetTimeDigitized",
        )
        if dt is not None:
            return dt

        return None

    def extract_gps_datetime(self) -> T.Optional[datetime.datetime]:
        """
        Extract timestamp from GPS field.
        """
        timestr = self._extract_alternative_fields(["exif:GPSTimeStamp"], str)
        if not timestr:
            return None

        # handle: <exif:GPSTimeStamp>2021-07-15T05:37:30Z</exif:GPSTimeStamp>
        dt = strptime_alternative_formats(timestr, ["ISO"])
        if dt is not None:
            return dt

        datestr = self._extract_alternative_fields(["exif:GPSDateStamp"], str)
        if datestr is None:
            return None

        # handle: exif:GPSTimeStamp="17:22:05.999000"
        return parse_gps_datetime_separately(datestr, timestr)

    def extract_capture_time(self) -> T.Optional[datetime.datetime]:
        dt = self.extract_gps_datetime()
        if dt is not None and dt.date() != datetime.date(1970, 1, 1):
            return dt

        dt = self.extract_exif_datetime()
        if dt is not None:
            return dt

        return None

    def extract_direction(self) -> T.Optional[float]:
        return self._extract_alternative_fields(
            ["exif:GPSImgDirection", "exif:GPSTrack"], float
        )

    def extract_lon_lat(self) -> T.Optional[T.Tuple[float, float]]:
        lat_ref = self._extract_alternative_fields(["exif:GPSLatitudeRef"], str)
        lat_str: T.Optional[str] = self._extract_alternative_fields(
            ["exif:GPSLatitude"], str
        )
        lat: T.Optional[float] = _parse_coord(lat_str, lat_ref)
        if lat is None:
            return None

        lon_ref = self._extract_alternative_fields(["exif:GPSLongitudeRef"], str)
        lon_str: T.Optional[str] = self._extract_alternative_fields(
            ["exif:GPSLongitude"], str
        )
        lon = _parse_coord(lon_str, lon_ref)
        if lon is None:
            return None

        return lon, lat

    def extract_make(self) -> T.Optional[str]:
        make = self._extract_alternative_fields(["tiff:Make", "exifEX:LensMake"], str)
        if make is None:
            return None
        return make.strip()

    def extract_model(self) -> T.Optional[str]:
        model = self._extract_alternative_fields(
            ["tiff:Model", "exifEX:LensModel"], str
        )
        if model is None:
            return None
        return model.strip()

    def extract_width(self) -> T.Optional[int]:
        return self._extract_alternative_fields(
            [
                "exif:PixelXDimension",
                "GPano:FullPanoWidthPixels",
                "GPano:CroppedAreaImageWidthPixels",
            ],
            int,
        )

    def extract_height(self) -> T.Optional[int]:
        return self._extract_alternative_fields(
            [
                "exif:PixelYDimension",
                "GPano:FullPanoHeightPixels",
                "GPano:CroppedAreaImageHeightPixels",
            ],
            int,
        )

    def extract_orientation(self) -> int:
        orientation = self._extract_alternative_fields(["tiff:Orientation"], int)
        if orientation is None or orientation not in range(1, 9):
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
            ns, attr_or_tag = field.split(":")
            value = self._tags_or_attrs.get(
                "{" + XMP_NAMESPACES[ns] + "}" + attr_or_tag
            )
            if value is None:
                continue
            if field_type is int:
                try:
                    return T.cast(_FIELD_TYPE, int(value))
                except (ValueError, TypeError):
                    pass
            elif field_type is float:
                try:
                    return T.cast(_FIELD_TYPE, float(value))
                except (ValueError, TypeError):
                    pass
            elif field_type is str:
                try:
                    return T.cast(_FIELD_TYPE, str(value))
                except (ValueError, TypeError):
                    pass
            else:
                raise ValueError(f"Invalid field type {field_type}")
        return None


class ExifReadFromEXIF(ExifReadABC):
    """
    EXIF class for reading exif from an image
    """

    def __init__(self, path_or_stream: T.Union[Path, T.BinaryIO]) -> None:
        """
        Initialize EXIF object with FILE as filename or fileobj
        """
        if isinstance(path_or_stream, Path):
            with path_or_stream.open("rb") as fp:
                try:
                    self.tags = exifread.process_file(fp, details=True, debug=True)
                except Exception:
                    self.tags = {}

        else:
            try:
                self.tags = exifread.process_file(
                    path_or_stream, details=True, debug=True
                )
            except Exception:
                self.tags = {}

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

        dt = strptime_alternative_formats(gpsdate, ["%Y:%m:%d", "%Y-%m-%d"])
        if dt is None or dt == datetime.date(1970, 1, 1):
            return None

        gpstimestamp = self.tags.get("GPS GPSTimeStamp")
        if not gpstimestamp:
            return None

        delta = parse_time_ratios_as_timedelta(gpstimestamp.values)
        if delta is None:
            return None

        dt = dt + delta

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
        dt = parse_datetimestr_with_subsec_and_offset(dtstr, subsec, offset)
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
        if gps_dt is not None and gps_dt.date() != datetime.date(1970, 1, 1):
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
        make = self._extract_alternative_fields(["Image Make", "EXIF LensMake"], str)
        if make is None:
            return None
        return make.strip()

    def extract_model(self) -> T.Optional[str]:
        """
        Extract camera model
        """
        model = self._extract_alternative_fields(["Image Model", "EXIF LensModel"], str)
        if model is None:
            return None
        return model.strip()

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
                if values:
                    if len(values) == 1 and isinstance(values[0], Ratio):
                        try:
                            return T.cast(_FIELD_TYPE, eval_frac(values[0]))
                        except ZeroDivisionError:
                            pass
            elif field_type is str:
                try:
                    return T.cast(_FIELD_TYPE, str(values))
                except (ValueError, TypeError):
                    pass
            elif field_type is int:
                if values:
                    try:
                        return T.cast(_FIELD_TYPE, int(values[0]))
                    except (ValueError, TypeError):
                        pass
            else:
                raise ValueError(f"Invalid field type {field_type}")
        return None

    def extract_application_notes(self) -> T.Optional[str]:
        xmp = self.tags.get("Image ApplicationNotes")
        if xmp is None:
            return None
        try:
            return str(xmp)
        except (ValueError, TypeError):
            return None


class ExifRead(ExifReadFromEXIF):
    def __init__(self, path_or_stream: T.Union[Path, T.BinaryIO]) -> None:
        super().__init__(path_or_stream)
        self._xmp = self._extract_xmp()

    def _extract_xmp(self) -> T.Optional[ExifReadFromXMP]:
        application_notes = self.extract_application_notes()
        if application_notes is None:
            return None
        try:
            e = et.fromstring(application_notes)
        except et.ParseError:
            return None
        return ExifReadFromXMP(et.ElementTree(e))

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
