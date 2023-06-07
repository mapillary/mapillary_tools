import typing as T
import xml.etree.ElementTree as et

from . import exif_read, geo


_FIELD_TYPE = T.TypeVar("_FIELD_TYPE", int, float, str, T.List[str])
MAX_TRACK_ID = 10
XMP_NAMESPACES: T.Dict[str, str] = {
    "Keys": "http://ns.exiftool.org/QuickTime/Keys/1.0/",
    "IFD0": "http://ns.exiftool.org/EXIF/IFD0/1.0/",
    "QuickTime": "http://ns.exiftool.org/QuickTime/QuickTime/1.0/",
    "UserData": "http://ns.exiftool.org/QuickTime/UserData/1.0/",
    "Insta360": "http://ns.exiftool.org/Trailer/Insta360/1.0/",
    "GoPro": "http://ns.exiftool.org/QuickTime/GoPro/1.0/",
    **{
        f"Track{track_id}": f"http://ns.exiftool.org/QuickTime/Track{track_id}/1.0/"
        for track_id in range(MAX_TRACK_ID)
    },
}


def maybe_float(text: T.Optional[str]) -> T.Optional[float]:
    if text is None:
        return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


class ExifToolReadVideo:
    def __init__(
        self,
        etree: et.ElementTree,
    ) -> None:
        self.etree = etree
        self._texts_by_tag: T.Dict[str, T.List[str]] = {}
        for element in self.etree.getroot():
            tag = element.tag
            if element.text is not None:
                self._texts_by_tag.setdefault(tag, []).append(element.text)

    def extract_gps_track_from_quicktime(self):
        return self._extract_gps_track_from(
            "QuickTime:GPSDateTime",
            "QuickTime:GPSLongitude",
            "QuickTime:GPSLatitude",
            "QuickTime:GPSAltitude",
            "QuickTime:GPSTrack",
        )

    def extract_gps_track_from_insta360(self):
        return self._extract_gps_track_from(
            "Insta360:GPSDateTime",
            "Insta360:GPSLongitude",
            "Insta360:GPSLatitude",
            "Insta360:GPSAltitude",
            "Insta360:GPSTrack",
        )

    def extract_gps_track_from_track(self):
        for track_id in range(MAX_TRACK_ID):
            track = self._extract_gps_track_from(
                f"Track{track_id}:GPSDateTime",
                f"Track{track_id}:GPSLongitude",
                f"Track{track_id}:GPSLatitude",
                f"Track{track_id}:GPSAltitude",
                f"Track{track_id}:GPSTrack",
            )
            if track:
                return track
        return []

    def extract_gps_track(self):
        track = self.extract_gps_track_from_quicktime()
        if track:
            return track

        track = self.extract_gps_track_from_insta360()
        if track:
            return track

        track = self.extract_gps_track_from_track()
        if track:
            return track

        return []

    def _extract_gps_track_from(
        self,
        time_tag: str,
        lon_tag: str,
        lat_tag: str,
        alt_tag: T.Optional[str] = None,
        direction_tag: T.Optional[str] = None,
    ) -> T.List[geo.Point]:
        gpsdatetimes = [
            exif_read.parse_gps_datetime(text)
            for text in self._extract_alternative_fields([time_tag], list) or []
        ]
        lons = [
            maybe_float(lon)
            for lon in self._extract_alternative_fields([lon_tag], list) or []
        ]
        lats = [
            maybe_float(lat)
            for lat in self._extract_alternative_fields([lat_tag], list) or []
        ]
        if alt_tag is not None:
            alts = [
                maybe_float(alt)
                for alt in self._extract_alternative_fields([alt_tag], list) or []
            ]
        else:
            alts = []

        expected_length = len(gpsdatetimes)
        if not (len(lats) == expected_length and len(lons) == expected_length):
            return []

        if direction_tag is not None:
            directions = [
                maybe_float(direction)
                for direction in self._extract_alternative_fields([direction_tag], list)
                or []
            ]
        else:
            directions = []
        while len(alts) < expected_length:
            alts.append(None)
        while len(directions) < expected_length:
            directions.append(None)

        track = []
        for dt, lon, lat, alt, direction in zip(
            gpsdatetimes, lons, lats, alts, directions
        ):
            if dt is None or lon is None or lat is None:
                continue
            track.append(
                geo.Point(
                    time=geo.as_unix_time(dt),
                    lon=lon,
                    lat=lat,
                    alt=alt,
                    angle=direction,
                )
            )
        track.sort(key=lambda point: point.time)

        if track:
            first_time = track[0].time
            for point in track:
                point.time = point.time - first_time

        deduplicated_track = []
        if track:
            prev = None
            for point in track:
                cur = (point.time, point.lon, point.lat)
                if prev is None or cur != prev:
                    deduplicated_track.append(point)
                prev = cur

        return deduplicated_track

    def extract_make(self) -> T.Optional[str]:
        make = self._extract_alternative_fields(
            ["IFD0:Make", "Keys:Make", "UserData:Make", "Insta360:Make", "GoPro:Make"],
            str,
        )
        if make is None:
            return None
        return make.strip()

    def extract_model(self) -> T.Optional[str]:
        model = self._extract_alternative_fields(
            [
                "IFD0:Model",
                "Keys:Model",
                "UserData:Model",
                "Insta360:Model",
                "GoPro:Model",
            ],
            str,
        )
        if model is None:
            return None
        return model.strip()

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
            values = self._texts_by_tag.get(
                "{" + XMP_NAMESPACES[ns] + "}" + attr_or_tag
            )
            if values is None:
                continue
            if field_type is int:
                value = values[0]
                try:
                    return T.cast(_FIELD_TYPE, int(value))
                except (ValueError, TypeError):
                    pass
            elif field_type is float:
                value = values[0]
                try:
                    return T.cast(_FIELD_TYPE, float(value))
                except (ValueError, TypeError):
                    pass
            elif field_type is str:
                value = values[0]
                try:
                    return T.cast(_FIELD_TYPE, str(value))
                except (ValueError, TypeError):
                    pass
            elif field_type is list:
                return T.cast(_FIELD_TYPE, values)
            else:
                raise ValueError(f"Invalid field type {field_type}")
        return None
