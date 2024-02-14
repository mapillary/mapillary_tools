import datetime
import logging
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

from . import exif_read, utils


EXIFTOOL_NAMESPACES: T.Dict[str, str] = {
    "Adobe": "http://ns.exiftool.org/APP14/Adobe/1.0/",
    "Apple": "http://ns.exiftool.org/MakerNotes/Apple/1.0/",
    "Composite": "http://ns.exiftool.org/Composite/1.0/",
    "ExifIFD": "http://ns.exiftool.org/EXIF/ExifIFD/1.0/",
    "ExifTool": "http://ns.exiftool.org/ExifTool/1.0/",
    "File": "http://ns.exiftool.org/File/1.0/",
    "GPS": "http://ns.exiftool.org/EXIF/GPS/1.0/",
    "GoPro": "http://ns.exiftool.org/APP6/GoPro/1.0/",
    "ICC-chrm": "http://ns.exiftool.org/ICC_Profile/ICC-chrm/1.0/",
    "ICC-header": "http://ns.exiftool.org/ICC_Profile/ICC-header/1.0/",
    "ICC-meas": "http://ns.exiftool.org/ICC_Profile/ICC-meas/1.0/",
    "ICC-view": "http://ns.exiftool.org/ICC_Profile/ICC-view/1.0/",
    "ICC_Profile": "http://ns.exiftool.org/ICC_Profile/ICC_Profile/1.0/",
    "IFD0": "http://ns.exiftool.org/EXIF/IFD0/1.0/",
    "IFD1": "http://ns.exiftool.org/EXIF/IFD1/1.0/",
    "IPTC": "http://ns.exiftool.org/IPTC/IPTC/1.0/",
    "InteropIFD": "http://ns.exiftool.org/EXIF/InteropIFD/1.0/",
    "JFIF": "http://ns.exiftool.org/JFIF/JFIF/1.0/",
    "MPF0": "http://ns.exiftool.org/MPF/MPF0/1.0/",
    "MPImage1": "http://ns.exiftool.org/MPF/MPImage1/1.0/",
    "MPImage2": "http://ns.exiftool.org/MPF/MPImage2/1.0/",
    "Photoshop": "http://ns.exiftool.org/Photoshop/Photoshop/1.0/",
    "Samsung": "http://ns.exiftool.org/MakerNotes/Samsung/1.0/",
    "System": "http://ns.exiftool.org/File/System/1.0/",
    "XMP-GAudio": "http://ns.exiftool.org/XMP/XMP-GAudio/1.0/",
    "XMP-GImage": "http://ns.exiftool.org/XMP/XMP-GImage/1.0/",
    "XMP-GPano": "http://ns.exiftool.org/XMP/XMP-GPano/1.0/",
    "XMP-aux": "http://ns.exiftool.org/XMP/XMP-aux/1.0/",
    "XMP-crs": "http://ns.exiftool.org/XMP/XMP-crs/1.0/",
    "XMP-dc": "http://ns.exiftool.org/XMP/XMP-dc/1.0/",
    "XMP-exif": "http://ns.exiftool.org/XMP/XMP-exif/1.0/",
    "XMP-exifEX": "http://ns.exiftool.org/XMP/XMP-exifEX/1.0/",
    "XMP-photoshop": "http://ns.exiftool.org/XMP/XMP-photoshop/1.0/",
    "XMP-tiff": "http://ns.exiftool.org/XMP/XMP-tiff/1.0/",
    "XMP-x": "http://ns.exiftool.org/XMP/XMP-x/1.0/",
    "XMP-xmp": "http://ns.exiftool.org/XMP/XMP-xmp/1.0/",
    "XMP-xmpMM": "http://ns.exiftool.org/XMP/XMP-xmpMM/1.0/",
    "XMP-xmpNote": "http://ns.exiftool.org/XMP/XMP-xmpNote/1.0/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
}


LOG = logging.getLogger(__name__)
_FIELD_TYPE = T.TypeVar("_FIELD_TYPE", int, float, str)
_DESCRIPTION_TAG = "rdf:Description"


def expand_tag(ns_tag: str, namespaces: T.Dict[str, str]) -> str:
    try:
        ns, tag = ns_tag.split(":", maxsplit=2)
    except ValueError:
        raise ValueError(f"Invalid tag {ns_tag}")
    return "{" + namespaces[ns] + "}" + tag


_EXPANDED_ABOUT_TAG = expand_tag("rdf:about", EXIFTOOL_NAMESPACES)


def canonical_path(path: Path) -> str:
    return str(path.resolve().as_posix())


def find_rdf_description_path(element: ET.Element) -> T.Optional[Path]:
    about = element.get(_EXPANDED_ABOUT_TAG)
    if about is None:
        return None
    return Path(about)


def index_rdf_description_by_path(
    xml_paths: T.Sequence[Path],
) -> T.Dict[str, ET.Element]:
    rdf_description_by_path: T.Dict[str, ET.Element] = {}

    for xml_path in utils.find_xml_files(xml_paths):
        try:
            etree = ET.parse(xml_path)
        except ET.ParseError as ex:
            verbose = LOG.getEffectiveLevel() <= logging.DEBUG
            if verbose:
                LOG.warning(f"Failed to parse {xml_path}", exc_info=verbose)
            else:
                LOG.warning(f"Failed to parse {xml_path}: {ex}", exc_info=verbose)
            continue

        elements = etree.iterfind(_DESCRIPTION_TAG, namespaces=EXIFTOOL_NAMESPACES)
        for element in elements:
            path = find_rdf_description_path(element)
            if path is not None:
                rdf_description_by_path[canonical_path(path)] = element

    return rdf_description_by_path


class ExifToolRead(exif_read.ExifReadABC):
    """
    Read exif from ExifTool XML output
    """

    def __init__(
        self,
        etree: ET.ElementTree,
    ) -> None:
        self.etree = etree

    def extract_altitude(self) -> T.Optional[float]:
        """
        Extract altitude
        """
        altitude = self._extract_alternative_fields(["GPS:GPSAltitude"], float)
        if altitude is None:
            return None
        # 0 = Above sea level
        # 1 = Below sea level
        ref = self._extract_alternative_fields(["GPS:GPSAltitudeRef"], int)
        if ref == 1:
            altitude = -1 * altitude
        return altitude

    def _extract_gps_datetime(
        self, date_tags: T.Sequence[str], time_tags: T.Sequence[str]
    ) -> T.Optional[datetime.datetime]:
        """
        Extract timestamp from GPS field.
        """
        gpsdate = self._extract_alternative_fields(date_tags, str)
        if gpsdate is None:
            return None

        gpstimestamp = self._extract_alternative_fields(time_tags, str)
        if not gpstimestamp:
            return None

        return exif_read.parse_gps_datetime_separately(gpsdate, gpstimestamp)

    def extract_gps_datetime(self) -> T.Optional[datetime.datetime]:
        """
        Extract timestamp from GPS field.
        """
        return self._extract_gps_datetime(["GPS:GPSDateStamp"], ["GPS:GPSTimeStamp"])

    def extract_gps_datetime_from_xmp(self) -> T.Optional[datetime.datetime]:
        """
        Extract timestamp from XMP GPS field.
        """
        # example: <XMP-exif:GPSDateStamp>2021:09:14</XMP-exif:GPSDateStamp>
        # example: <XMP-exif:GPSDateTime>08:23:56.000000</XMP-exif:GPSDateTime>
        return self._extract_gps_datetime(
            ["XMP-exif:GPSDateStamp"],
            # Put both here but I do not see any XMP-exif:GPSTimeStamp in my samples
            ["XMP-exif:GPSDateTime", "XMP-exif:GPSTimeStamp"],
        )

    def _extract_exif_datetime(
        self,
        dt_tags: T.Sequence[str],
        subsec_tags: T.Sequence[str],
        offset_tags: T.Sequence[str],
    ) -> T.Optional[datetime.datetime]:
        dtstr = self._extract_alternative_fields(dt_tags, str)
        if dtstr is None:
            return None
        subsec = self._extract_alternative_fields(subsec_tags, str)
        # See https://github.com/mapillary/mapillary_tools/issues/388#issuecomment-860198046
        # and https://community.gopro.com/t5/Cameras/subsecond-timestamp-bug/m-p/1057505
        if subsec:
            subsec = subsec.replace(" ", "0")
        offset = self._extract_alternative_fields(offset_tags, str)
        dt = exif_read.parse_datetimestr_with_subsec_and_offset(dtstr, subsec, offset)
        if dt is None:
            return None
        return dt

    def extract_exif_datetime_from_xmp(self) -> T.Optional[datetime.datetime]:
        # EXIF DateTimeOriginal: 0x9003 (date/time when original image was taken)
        # EXIF SubSecTimeOriginal: 0x9291 (fractional seconds for DateTimeOriginal)
        # EXIF OffsetTimeOriginal: 0x9011 (time zone for DateTimeOriginal)
        dt = self._extract_exif_datetime(
            ["XMP-exif:DateTimeOriginal"],
            # NOTE: it is Subsec instead of SubSec
            ["XMP-exif:SubsecTimeOriginal"],
            ["XMP-exif:OffsetTimeOriginal"],
        )
        if dt is not None:
            return dt

        # EXIF DateTimeDigitized: 0x9004 CreateDate in ExifTool (called DateTimeDigitized by the EXIF spec.)
        # EXIF SubSecTimeDigitized: 0x9292 (fractional seconds for CreateDate)
        # EXIF OffsetTimeDigitized: 0x9012 (time zone for CreateDate)
        dt = self._extract_exif_datetime(
            ["XMP-exif:DateTimeDigitized", "XMP-xmp:CreateDate"],
            # NOTE: it is Subsec instead of SubSec
            ["XMP-exif:SubsecTimeDigitized"],
            ["XMP-exif:OffsetTimeDigitized"],
        )
        if dt is not None:
            return dt

        # Image DateTime: 0x0132 ModifyDate in ExifTool (called DateTime by the EXIF spec.)
        # EXIF SubSecTime: 0x9290 (fractional seconds for ModifyDate)
        # EXIF OffsetTime: 0x9010 (time zone for ModifyDate)
        dt = self._extract_exif_datetime(
            ["XMP-exif:ModifyDate"],
            # NOTE: this tag might not exist in XMP
            ["XMP-exif:SubsecTime"],
            ["XMP-exif:OffsetTime"],
        )
        if dt is not None:
            return dt

        return None

    def extract_exif_datetime(self) -> T.Optional[datetime.datetime]:
        # EXIF DateTimeOriginal: 0x9003 (date/time when original image was taken)
        # EXIF SubSecTimeOriginal: 0x9291 (fractional seconds for DateTimeOriginal)
        # EXIF OffsetTimeOriginal: 0x9011 (time zone for DateTimeOriginal)
        dt = self._extract_exif_datetime(
            ["ExifIFD:DateTimeOriginal"],
            ["ExifIFD:SubSecTimeOriginal"],
            ["ExifIFD:OffsetTimeOriginal"],
        )
        if dt is not None:
            return dt

        # EXIF DateTimeDigitized: 0x9004 CreateDate in ExifTool (called DateTimeDigitized by the EXIF spec.)
        # EXIF SubSecTimeDigitized: 0x9292 (fractional seconds for CreateDate)
        # EXIF OffsetTimeDigitized: 0x9012 (time zone for CreateDate)
        dt = self._extract_exif_datetime(
            ["ExifIFD:CreateDate"],
            ["ExifIFD:SubSecTimeDigitized"],
            ["ExifIFD:OffsetTimeDigitized"],
        )
        if dt is not None:
            return dt

        # Image DateTime: 0x0132 ModifyDate in ExifTool (called DateTime by the EXIF spec.)
        # EXIF SubSecTime: 0x9290 (fractional seconds for ModifyDate)
        # EXIF OffsetTime: 0x9010 (time zone for ModifyDate)
        dt = self._extract_exif_datetime(
            ["ExifIFD:ModifyDate", "IFD0:ModifyDate", "IFD1:ModifyDate"],
            ["ExifIFD:SubSecTime"],
            ["ExifIFD:OffsetTime"],
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
            dt = self.extract_gps_datetime()
        except (ValueError, TypeError, ZeroDivisionError):
            dt = None
        if dt is not None and dt.date() != datetime.date(1970, 1, 1):
            return dt

        try:
            dt = self.extract_gps_datetime_from_xmp()
        except (ValueError, TypeError, ZeroDivisionError):
            dt = None
        if dt is not None and dt.date() != datetime.date(1970, 1, 1):
            return dt

        dt = self.extract_exif_datetime()
        if dt is not None:
            return dt

        dt = self.extract_exif_datetime_from_xmp()
        if dt is not None:
            return dt

        return None

    def extract_direction(self) -> T.Optional[float]:
        """
        Extract image direction (i.e. compass, heading, bearing)
        """
        # https://www.awaresystems.be/imaging/tiff/tifftags/privateifd/gps/gpsimgdirectionref.html
        return self._extract_alternative_fields(
            [
                "GPS:GPSImgDirection",
                "GPS:GPSTrack",
            ],
            float,
        )

    def extract_lon_lat(self) -> T.Optional[T.Tuple[float, float]]:
        lon_lat = self._extract_lon_lat("GPS:GPSLongitude", "GPS:GPSLatitude")
        if lon_lat is not None:
            return lon_lat

        lon_lat = self._extract_lon_lat(
            "Composite:GPSLongitude", "Composite:GPSLatitude"
        )
        if lon_lat is not None:
            return lon_lat

        lon_lat = self._extract_lon_lat("XMP-exif:GPSLongitude", "XMP-exif:GPSLatitude")
        if lon_lat is not None:
            return lon_lat

        return None

    def _extract_lon_lat(
        self, lon_tag: str, lat_tag: str
    ) -> T.Optional[T.Tuple[float, float]]:
        lon = self._extract_alternative_fields(
            [lon_tag],
            float,
        )
        if lon is None:
            return None
        ref = self._extract_alternative_fields([lon_tag + "Ref"], str)
        if ref and ref.upper() in ["WEST", "W"]:
            lon = -1 * lon

        lat = self._extract_alternative_fields(
            [lat_tag],
            float,
        )
        if lat is None:
            return None
        ref = self._extract_alternative_fields([lat_tag + "Ref"], str)
        if ref and ref.upper() in ["SOUTH", "S"]:
            lat = -1 * lat

        return lon, lat

    def extract_make(self) -> T.Optional[str]:
        """
        Extract camera make
        """
        make = self._extract_alternative_fields(
            [
                "IFD0:Make",
                "IFD1:Make",
                "ExifIFD:Make",
                "ExifIFD:LensMake",
                "XMP-exif:Make",
                "XMP-exifEX:LensMake",
            ],
            str,
        )
        if make is None:
            return None
        return make.strip()

    def extract_model(self) -> T.Optional[str]:
        """
        Extract camera model
        """
        model = self._extract_alternative_fields(
            [
                "IFD0:Model",
                "IFD1:Model",
                "ExifIFD:Model",
                "GoPro:Model",
                "ExifIFD:LensModel",
                "XMP-exif:Model",
                "XMP-exifEX:LensModel",
            ],
            str,
        )
        if model is None:
            return None
        return model.strip()

    def extract_width(self) -> T.Optional[int]:
        """
        Extract image width in pixels
        """
        return self._extract_alternative_fields(
            [
                "File:ImageWidth",
                "ExifIFD:ExifImageWidth",
                "IFD0:ExifImageWidth",
                "IFD1:ExifImageWidth",
                "XMP-exif:ExifImageWidth",
            ],
            int,
        )

    def extract_height(self) -> T.Optional[int]:
        """
        Extract image height in pixels
        """
        return self._extract_alternative_fields(
            [
                "File:ImageHeight",
                "ExifIFD:ExifImageHeight",
                "IFD0:ExifImageHeight",
                "IFD1:ExifImageHeight",
                "XMP-exif:ExifImageHeight",
            ],
            int,
        )

    def extract_orientation(self) -> int:
        """
        Extract image orientation
        """
        orientation = self._extract_alternative_fields(
            [
                "ExifIFD:Orientation",
                "IFD0:Orientation",
                "IFD1:Orientation",
                "XMP-exif:Orientation",
                "XMP-tiff:Orientation",
            ],
            int,
        )
        if orientation is None:
            return 1
        if orientation not in range(1, 9):
            return 1
        return orientation

    def _extract_alternative_fields(
        self,
        fields: T.Sequence[str],
        field_type: T.Type[_FIELD_TYPE],
    ) -> T.Optional[_FIELD_TYPE]:
        for field in fields:
            value = self.etree.findtext(field, namespaces=EXIFTOOL_NAMESPACES)
            if value is None:
                continue
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
