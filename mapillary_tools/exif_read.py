from __future__ import annotations

import abc
import datetime
import io
import logging
import re
import struct
import typing as T
import xml.etree.ElementTree as et
from fractions import Fraction
from pathlib import Path

import exifread
from exifread.utils import Ratio


LOG = logging.getLogger(__name__)
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


def gps_to_decimal(values: tuple[Ratio, Ratio, Ratio]) -> float | None:
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


def _parse_coord_numeric(coord: str, ref: str | None) -> float | None:
    try:
        return float(coord) * SIGN_BY_DIRECTION[ref]
    except (ValueError, KeyError):
        return None


def _parse_coord_adobe(coord: str) -> float | None:
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


def _parse_coord(coord: str | None, ref: str | None) -> float | None:
    if coord is None:
        return None
    parsed = _parse_coord_numeric(coord, ref)
    if parsed is None:
        parsed = _parse_coord_adobe(coord)
    return parsed


def _parse_iso(dtstr: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(dtstr)
    except ValueError:
        # fromisoformat does not support trailing Z
        return strptime_alternative_formats(
            dtstr, ["%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"]
        )


def strptime_alternative_formats(
    dtstr: str, formats: list[str]
) -> datetime.datetime | None:
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


def parse_timestr_as_timedelta(timestr: str) -> datetime.timedelta | None:
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
    time_tuple: list[Ratio],
) -> datetime.timedelta | None:
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
    default_tz: datetime.timezone | None = datetime.timezone.utc,
) -> datetime.datetime | None:
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
    default_tz: datetime.timezone | None = datetime.timezone.utc,
) -> datetime.datetime | None:
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
    dtstr: str, subsec: str | None = None, tz_offset: str | None = None
) -> datetime.datetime | None:
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
    def extract_altitude(self) -> float | None:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_capture_time(self) -> datetime.datetime | None:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_direction(self) -> float | None:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_lon_lat(self) -> tuple[float, float] | None:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_make(self) -> str | None:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_model(self) -> str | None:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_width(self) -> int | None:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_height(self) -> int | None:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_orientation(self) -> int:
        raise NotImplementedError


class ExifReadFromXMP(ExifReadABC):
    def __init__(self, etree: et.ElementTree):
        self.etree = etree
        self._tags_or_attrs: dict[str, str] = {}
        for description in self.etree.iterfind(
            ".//rdf:Description", namespaces=XMP_NAMESPACES
        ):
            for k, v in description.items():
                self._tags_or_attrs[k] = v
            for child in description:
                if child.text is not None:
                    self._tags_or_attrs[child.tag] = child.text

    def extract_altitude(self) -> float | None:
        return self._extract_alternative_fields(["exif:GPSAltitude"], float)

    def _extract_exif_datetime(
        self, dt_tag: str, subsec_tag: str, offset_tag: str
    ) -> datetime.datetime | None:
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

    def extract_exif_datetime(self) -> datetime.datetime | None:
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

    def extract_gps_datetime(self) -> datetime.datetime | None:
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

    def extract_capture_time(self) -> datetime.datetime | None:
        dt = self.extract_gps_datetime()
        if dt is not None and dt.date() != datetime.date(1970, 1, 1):
            return dt

        dt = self.extract_exif_datetime()
        if dt is not None:
            return dt

        return None

    def extract_direction(self) -> float | None:
        return self._extract_alternative_fields(
            ["exif:GPSImgDirection", "exif:GPSTrack"], float
        )

    def extract_lon_lat(self) -> tuple[float, float] | None:
        lat_ref = self._extract_alternative_fields(["exif:GPSLatitudeRef"], str)
        lat_str: str | None = self._extract_alternative_fields(
            ["exif:GPSLatitude"], str
        )
        lat: float | None = _parse_coord(lat_str, lat_ref)
        if lat is None:
            return None

        lon_ref = self._extract_alternative_fields(["exif:GPSLongitudeRef"], str)
        lon_str: str | None = self._extract_alternative_fields(
            ["exif:GPSLongitude"], str
        )
        lon = _parse_coord(lon_str, lon_ref)
        if lon is None:
            return None

        return lon, lat

    def extract_make(self) -> str | None:
        make = self._extract_alternative_fields(["tiff:Make", "exifEX:LensMake"], str)
        if make is None:
            return None
        return make.strip()

    def extract_model(self) -> str | None:
        model = self._extract_alternative_fields(
            ["tiff:Model", "exifEX:LensModel"], str
        )
        if model is None:
            return None
        return model.strip()

    def extract_width(self) -> int | None:
        return self._extract_alternative_fields(
            [
                "exif:PixelXDimension",
                "GPano:FullPanoWidthPixels",
                "GPano:CroppedAreaImageWidthPixels",
            ],
            int,
        )

    def extract_height(self) -> int | None:
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
        fields: T.Iterable[str],
        field_type: type[_FIELD_TYPE],
    ) -> _FIELD_TYPE | None:
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


def extract_xmp_efficiently(fp) -> str | None:
    """
    Extract XMP metadata from a JPEG file efficiently by reading only necessary chunks.

    Args:
        image_path (str): Path to the JPEG image file

    Returns:
        str: Formatted XML string containing XMP metadata, or None if no XMP data found
    """
    # JPEG markers
    SOI_MARKER = b"\xff\xd8"  # Start of Image
    APP1_MARKER = b"\xff\xe1"  # Application Segment 1 (where XMP usually lives)
    XMP_IDENTIFIER = b"http://ns.adobe.com/xap/1.0/\x00"
    XMP_META_TAG_BEGIN = b"<x:xmpmeta"
    XMP_META_TAG_END = b"</x:xmpmeta>"

    # Check for JPEG signature (SOI marker)
    if fp.read(2) != SOI_MARKER:
        return None

    while True:
        # Read marker
        marker_bytes = fp.read(2)
        if len(marker_bytes) < 2:
            # End of file
            break

        # If not APP1, skip this segment
        if marker_bytes != APP1_MARKER:
            # Read length field (includes the length bytes themselves)
            length_bytes = fp.read(2)
            if len(length_bytes) < 2:
                break

            length = struct.unpack(">H", length_bytes)[0]
            # Skip the rest of this segment (-2 because length includes length bytes)
            fp.seek(length - 2, io.SEEK_CUR)
            continue

        # It's an APP1 segment - read length
        length_bytes = fp.read(2)
        if len(length_bytes) < 2:
            break

        length = struct.unpack(">H", length_bytes)[0]
        segment_data_length = length - 2  # Subtract length field size

        # Read enough bytes to check for XMP identifier
        identifier_check = fp.read(len(XMP_IDENTIFIER))
        if len(identifier_check) < len(XMP_IDENTIFIER):
            break

        # Check if this APP1 contains XMP data
        if identifier_check == XMP_IDENTIFIER:
            # We found XMP data - read the rest of the segment
            remaining_length = segment_data_length - len(XMP_IDENTIFIER)
            if remaining_length > 128 * 1024 * 1024:
                raise ValueError("XMP data too large")
            xmp_data = fp.read(remaining_length)

            # Process the XMP data
            begin_idx = xmp_data.find(XMP_META_TAG_BEGIN)
            if begin_idx >= 0:
                end_idx = xmp_data.rfind(XMP_META_TAG_END, begin_idx)
                if end_idx >= 0:
                    xmp_data = xmp_data[begin_idx : end_idx + len(XMP_META_TAG_END)]
                else:
                    xmp_data = xmp_data[begin_idx:]

            return xmp_data.decode("utf-8")
        else:
            # Not XMP data - skip the rest of this APP1 segment
            # We already read the identifier_check bytes, so subtract that
            fp.seek(segment_data_length - len(identifier_check), io.SEEK_CUR)

    # If we reach here, no XMP data was found
    return None


class ExifReadFromEXIF(ExifReadABC):
    """
    EXIF class for reading exif from an image
    """

    def __init__(self, path_or_stream: Path | T.BinaryIO) -> None:
        """
        Initialize EXIF object with FILE as filename or fileobj
        """
        if isinstance(path_or_stream, Path):
            with path_or_stream.open("rb") as fp:
                try:
                    # Turn off details and debug for performance reasons
                    self.tags = exifread.process_file(fp, details=False, debug=False)
                except Exception as ex:
                    LOG.warning("Error reading EXIF from %s: %s", path_or_stream, ex)
                    self.tags = {}

        else:
            try:
                # Turn off details and debug for performance reasons
                self.tags = exifread.process_file(
                    path_or_stream, details=False, debug=False
                )
            except Exception as ex:
                LOG.warning("Error reading EXIF: %s", ex)
                self.tags = {}

    def extract_altitude(self) -> float | None:
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

    def extract_gps_datetime(self) -> datetime.datetime | None:
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
    ) -> datetime.datetime | None:
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

    def extract_exif_datetime(self) -> datetime.datetime | None:
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

    def extract_capture_time(self) -> datetime.datetime | None:
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

    def extract_direction(self) -> float | None:
        """
        Extract image direction (i.e. compass, heading, bearing)
        """
        fields = [
            "GPS GPSImgDirection",
            "GPS GPSTrack",
        ]
        return self._extract_alternative_fields(fields, float)

    def extract_lon_lat(self) -> tuple[float, float] | None:
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

    def extract_make(self) -> str | None:
        """
        Extract camera make
        """
        make = self._extract_alternative_fields(
            ["Image Make", "EXIF Make", "EXIF LensMake"], str
        )
        if make is None:
            return None
        return make.strip()

    def extract_model(self) -> str | None:
        """
        Extract camera model
        """
        model = self._extract_alternative_fields(
            ["Image Model", "EXIF Model", "EXIF LensModel"], str
        )
        if model is None:
            return None
        return model.strip()

    def extract_width(self) -> int | None:
        """
        Extract image width in pixels
        """
        return self._extract_alternative_fields(
            ["Image ImageWidth", "EXIF ExifImageWidth"], int
        )

    def extract_height(self) -> int | None:
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
        fields: T.Iterable[str],
        field_type: type[_FIELD_TYPE],
    ) -> _FIELD_TYPE | None:
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

    def extract_application_notes(self) -> str | None:
        xmp = self.tags.get("Image ApplicationNotes")
        if xmp is None:
            return None
        try:
            return str(xmp)
        except (ValueError, TypeError):
            return None


class ExifRead(ExifReadFromEXIF):
    """
    Extract properties from EXIF first and then XMP
    NOTE: For performance reasons, XMP is only extracted if EXIF does not contain the required fields
    """

    def __init__(self, path_or_stream: Path | T.BinaryIO) -> None:
        super().__init__(path_or_stream)
        self._path_or_stream = path_or_stream
        self._xml_extracted: bool = False
        self._cached_xml: ExifReadFromXMP | None = None

    def _xmp_with_reason(self, reason: str) -> ExifReadFromXMP | None:
        if not self._xml_extracted:
            LOG.debug('Extracting XMP for "%s"', reason)
            self._cached_xml = self._extract_xmp()
            self._xml_extracted = True

        return self._cached_xml

    def _extract_xmp(self) -> ExifReadFromXMP | None:
        xml_str = self.extract_application_notes()
        if xml_str is None:
            if isinstance(self._path_or_stream, Path):
                with self._path_or_stream.open("rb") as fp:
                    xml_str = extract_xmp_efficiently(fp)
            else:
                self._path_or_stream.seek(0, io.SEEK_SET)
                xml_str = extract_xmp_efficiently(self._path_or_stream)

            if xml_str is None:
                return None

        try:
            e = et.fromstring(xml_str)
        except et.ParseError as ex:
            LOG.warning("Error parsing XMP XML: %s: %s", ex, xml_str)
            return None

        return ExifReadFromXMP(et.ElementTree(e))

    def extract_altitude(self) -> float | None:
        val = super().extract_altitude()
        if val is not None:
            return val
        xmp = self._xmp_with_reason("altitude")
        if xmp is None:
            return None
        val = xmp.extract_altitude()
        if val is not None:
            return val
        return None

    def extract_capture_time(self) -> datetime.datetime | None:
        val = super().extract_capture_time()
        if val is not None:
            return val
        xmp = self._xmp_with_reason("capture_time")
        if xmp is None:
            return None
        val = xmp.extract_capture_time()
        if val is not None:
            return val
        return None

    def extract_lon_lat(self) -> tuple[float, float] | None:
        val = super().extract_lon_lat()
        if val is not None:
            return val
        xmp = self._xmp_with_reason("lon_lat")
        if xmp is None:
            return None
        val = xmp.extract_lon_lat()
        if val is not None:
            return val
        return None

    def extract_make(self) -> str | None:
        val = super().extract_make()
        if val is not None:
            return val
        xmp = self._xmp_with_reason("make")
        if xmp is None:
            return None
        val = xmp.extract_make()
        if val is not None:
            return val
        return None

    def extract_model(self) -> str | None:
        val = super().extract_model()
        if val is not None:
            return val
        xmp = self._xmp_with_reason("model")
        if xmp is None:
            return None
        val = xmp.extract_model()
        if val is not None:
            return val
        return None

    def extract_width(self) -> int | None:
        val = super().extract_width()
        if val is not None:
            return val
        xmp = self._xmp_with_reason("width")
        if xmp is None:
            return None
        val = xmp.extract_width()
        if val is not None:
            return val
        return None

    def extract_height(self) -> int | None:
        val = super().extract_height()
        if val is not None:
            return val
        xmp = self._xmp_with_reason("width")
        if xmp is None:
            return None
        val = xmp.extract_height()
        if val is not None:
            return val
        return None
