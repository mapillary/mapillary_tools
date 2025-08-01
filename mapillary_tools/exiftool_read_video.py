from __future__ import annotations

import dataclasses
import functools
import logging
import typing as T
import xml.etree.ElementTree as ET

from . import exif_read, exiftool_read, geo
from .telemetry import GPSFix, GPSPoint


MAX_TRACK_ID = 10
EXIFTOOL_NAMESPACES: dict[str, str] = {
    "Keys": "http://ns.exiftool.org/QuickTime/Keys/1.0/",
    "IFD0": "http://ns.exiftool.org/EXIF/IFD0/1.0/",
    "QuickTime": "http://ns.exiftool.org/QuickTime/QuickTime/1.0/",
    "UserData": "http://ns.exiftool.org/QuickTime/UserData/1.0/",
    "Insta360": "http://ns.exiftool.org/Trailer/Insta360/1.0/",
    "GoPro": "http://ns.exiftool.org/QuickTime/GoPro/1.0/",
    **{
        f"Track{track_id}": f"http://ns.exiftool.org/QuickTime/Track{track_id}/1.0/"
        for track_id in range(1, MAX_TRACK_ID + 1)
    },
}
LOG = logging.getLogger(__name__)
_FIELD_TYPE = T.TypeVar("_FIELD_TYPE", int, float, str, T.List[str])


expand_tag = functools.partial(exiftool_read.expand_tag, namespaces=EXIFTOOL_NAMESPACES)


def _maybe_float(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def _index_text_by_tag(elements: T.Iterable[ET.Element]) -> dict[str, list[str]]:
    texts_by_tag: dict[str, list[str]] = {}
    for element in elements:
        tag = element.tag
        if element.text is not None:
            texts_by_tag.setdefault(tag, []).append(element.text)
    return texts_by_tag


def _extract_alternative_fields(
    texts_by_tag: dict[str, list[str]],
    fields: T.Sequence[str],
    field_type: T.Type[_FIELD_TYPE],
) -> _FIELD_TYPE | None:
    for field in fields:
        values = texts_by_tag.get(expand_tag(field))
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


def _same_gps_point(left: GPSPoint, right: GPSPoint) -> bool:
    """
    >>> left =  GPSPoint(time=56.0, lat=36.741385, lon=29.021274, alt=141.6, angle=1.54, epoch_time=None, fix=None, precision=None, ground_speed=None)
    >>> right = GPSPoint(time=56.0, lat=36.741385, lon=29.021274, alt=142.4, angle=1.54, epoch_time=None, fix=None, precision=None, ground_speed=None)
    >>> _same_gps_point(left, right)
    True
    """
    return (
        left.time == right.time
        and left.lon == right.lon
        and left.lat == right.lat
        and left.epoch_time == right.epoch_time
        and left.angle == right.angle
    )


def _deduplicate_gps_points(
    track: list[GPSPoint], same_gps_point: T.Callable[[GPSPoint, GPSPoint], bool]
) -> list[GPSPoint]:
    deduplicated_track: list[GPSPoint] = []
    for point in track:
        if not deduplicated_track or not same_gps_point(deduplicated_track[-1], point):
            deduplicated_track.append(point)
    return deduplicated_track


def _aggregate_gps_track(
    texts_by_tag: dict[str, list[str]],
    time_tag: str | None,
    lon_tag: str,
    lat_tag: str,
    alt_tag: str | None = None,
    gps_time_tag: str | None = None,
    direction_tag: str | None = None,
    ground_speed_tag: str | None = None,
) -> list[GPSPoint]:
    """
    Aggregate all GPS data by the tags.
    It requires lat, lon to be present, and their lengths must match.
    Some cameras store time information in the SimpleTime tag (and each simple has multiple GPS data points),
    therefore the time_tag is optional. If it is None, then all returned points will have time = 0.0.
    """

    # aggregate coordinates (required)
    lons = [
        _maybe_float(lon)
        for lon in _extract_alternative_fields(texts_by_tag, [lon_tag], list) or []
    ]
    lats = [
        _maybe_float(lat)
        for lat in _extract_alternative_fields(texts_by_tag, [lat_tag], list) or []
    ]

    if len(lons) != len(lats):
        # no idea what to do if we have different number of lons and lats
        LOG.warning(
            "Found different number of longitudes %d and latitudes %d",
            len(lons),
            len(lats),
        )
        return []

    expected_length = len(lats)

    # aggregate timestamps (optional)
    if time_tag is not None:
        dts = [
            exif_read.parse_gps_datetime(text)
            for text in _extract_alternative_fields(texts_by_tag, [time_tag], list)
            or []
        ]
        timestamps = [geo.as_unix_time(dt) if dt is not None else None for dt in dts]
        if expected_length != len(timestamps):
            # no idea what to do if we have different number of timestamps and coordinates
            LOG.warning(
                "Found different number of timestamps %d and coordinates %d",
                len(timestamps),
                expected_length,
            )
            return []
    else:
        timestamps = [0.0] * expected_length

    assert len(timestamps) == expected_length

    def _aggregate_float_values_same_length(
        tag: str | None,
    ) -> list[float | None]:
        if tag is not None:
            vals = [
                _maybe_float(val)
                for val in _extract_alternative_fields(texts_by_tag, [tag], list) or []
            ]
        else:
            vals = []
        while len(vals) < expected_length:
            vals.append(None)
        return vals

    # aggregate altitudes (optional)
    alts = _aggregate_float_values_same_length(alt_tag)

    # aggregate directions (optional)
    directions = _aggregate_float_values_same_length(direction_tag)

    # aggregate speeds (optional)
    ground_speeds = _aggregate_float_values_same_length(ground_speed_tag)

    # GPS timestamp (optional)
    epoch_time = None
    if gps_time_tag is not None:
        gps_time_text = _extract_alternative_fields(texts_by_tag, [gps_time_tag], str)
        if gps_time_text is not None:
            dt = exif_read.parse_gps_datetime(gps_time_text)
            if dt is not None:
                epoch_time = geo.as_unix_time(dt)

    # build track
    track: list[GPSPoint] = []
    for timestamp, lon, lat, alt, direction, ground_speed in zip(
        timestamps,
        lons,
        lats,
        alts,
        directions,
        ground_speeds,
    ):
        if timestamp is None or lon is None or lat is None:
            continue

        point = GPSPoint(
            time=timestamp,
            lon=lon,
            lat=lat,
            alt=alt,
            angle=direction,
            epoch_time=epoch_time,
            fix=None,
            precision=None,
            ground_speed=ground_speed,
        )

        if not track or not _same_gps_point(track[-1], point):
            track.append(point)

    track.sort(key=lambda point: point.time)

    track = _deduplicate_gps_points(track, same_gps_point=_same_gps_point)

    if time_tag is not None:
        if track:
            first_time = track[0].time
            for point in track:
                point.time = point.time - first_time

    return track


def _aggregate_samples(
    elements: T.Iterable[ET.Element],
    sample_time_tag: str,
    sample_duration_tag: str,
) -> T.Generator[tuple[float, float, list[ET.Element]], None, None]:
    expanded_sample_time_tag = expand_tag(sample_time_tag)
    expanded_sample_duration_tag = expand_tag(sample_duration_tag)

    accumulated_elements: list[ET.Element] = []
    sample_time = None
    sample_duration = None
    for element in elements:
        if element.tag == expanded_sample_time_tag:
            if sample_time is not None and sample_duration is not None:
                yield (sample_time, sample_duration, accumulated_elements)
            accumulated_elements = []
            sample_time = _maybe_float(element.text)
        elif element.tag == expanded_sample_duration_tag:
            sample_duration = _maybe_float(element.text)
        else:
            accumulated_elements.append(element)
    if sample_time is not None and sample_duration is not None:
        yield (sample_time, sample_duration, accumulated_elements)


def _aggregate_gps_track_by_sample_time(
    sample_iterator: T.Iterable[tuple[float, float, list[ET.Element]]],
    lon_tag: str,
    lat_tag: str,
    alt_tag: str | None = None,
    gps_time_tag: str | None = None,
    direction_tag: str | None = None,
    ground_speed_tag: str | None = None,
    gps_fix_tag: str | None = None,
    gps_precision_tag: str | None = None,
) -> list[GPSPoint]:
    track: list[GPSPoint] = []

    expanded_gps_fix_tag = None
    if gps_fix_tag is not None:
        expanded_gps_fix_tag = expand_tag(gps_fix_tag)

    expanded_gps_precision_tag = None
    if gps_precision_tag is not None:
        expanded_gps_precision_tag = expand_tag(gps_precision_tag)

    for sample_time, sample_duration, elements in sample_iterator:
        texts_by_tag = _index_text_by_tag(elements)

        gps_fix = None
        if expanded_gps_fix_tag is not None:
            gps_fix_texts = texts_by_tag.get(expanded_gps_fix_tag)
            if gps_fix_texts:
                try:
                    gps_fix = GPSFix(int(gps_fix_texts[0]))
                except ValueError:
                    gps_fix = None

        gps_precision = None
        if expanded_gps_precision_tag is not None:
            gps_precision_texts = texts_by_tag.get(expanded_gps_precision_tag)
            if gps_precision_texts:
                gps_precision = _maybe_float(gps_precision_texts[0])
                if gps_precision is not None:
                    # GPS precision in ExifTool (i.e. horizontal positioning error) are in meters.
                    # https://exiftool.org/forum/index.php?topic=11565.0
                    # Here we multiply by 100 to be compatible with the GPSP
                    # described in https://github.com/gopro/gpmf-parser
                    gps_precision = gps_precision * 100

        # Aggregate GPS points in the sample
        points = _aggregate_gps_track(
            texts_by_tag,
            time_tag=None,
            lon_tag=lon_tag,
            lat_tag=lat_tag,
            alt_tag=alt_tag,
            direction_tag=direction_tag,
            ground_speed_tag=ground_speed_tag,
        )
        if points:
            avg_timedelta = sample_duration / len(points)
            for idx, point in enumerate(points):
                point.time = sample_time + idx * avg_timedelta
            track.extend(
                dataclasses.replace(point, fix=gps_fix, precision=gps_precision)
                for point in points
            )

    track.sort(key=lambda point: point.time)

    return track


class ExifToolReadVideo:
    def __init__(
        self,
        etree: ET.ElementTree,
    ) -> None:
        self.etree = etree
        root = self.etree.getroot()
        if root is None:
            raise ValueError("ElementTree root is None")
        self._texts_by_tag = _index_text_by_tag(root)
        self._all_tags = set(self._texts_by_tag.keys())

    def extract_gps_track(self) -> list[geo.Point]:
        # blackvue and many other cameras
        track_with_fix = self._extract_gps_track_from_quicktime()
        if track_with_fix:
            return T.cast(T.List[geo.Point], track_with_fix)

        # insta360 has its own tag
        track_with_fix = self._extract_gps_track_from_quicktime(namespace="Insta360")
        if track_with_fix:
            return T.cast(T.List[geo.Point], track_with_fix)

        # mostly for gopro
        track_with_fix = self._extract_gps_track_from_track()
        if track_with_fix:
            return T.cast(T.List[geo.Point], track_with_fix)

        return []

    def _extract_make_and_model(self) -> tuple[str | None, str | None]:
        make = self._extract_alternative_fields(["GoPro:Make"], str)
        model = self._extract_alternative_fields(["GoPro:Model"], str)
        if model is not None:
            if make is None:
                make = "GoPro"
            make = make.strip()
            model = model.strip()
            return make, model

        make = self._extract_alternative_fields(["Insta360:Make"], str)
        model = self._extract_alternative_fields(["Insta360:Model"], str)
        if model is not None:
            if make is None:
                make = "Insta360"
            make = make.strip()
            model = model.strip()
            return make, model

        make = self._extract_alternative_fields(
            ["IFD0:Make", "UserData:Make", "Keys:Make"], str
        )
        model = self._extract_alternative_fields(
            ["IFD0:Model", "UserData:Model", "Keys:Model"], str
        )
        if make is not None:
            make = make.strip()
        if model is not None:
            model = model.strip()
        return make, model

    def extract_make(self) -> str | None:
        make, _ = self._extract_make_and_model()
        return make

    def extract_model(self) -> str | None:
        _, model = self._extract_make_and_model()
        return model

    def _extract_gps_track_from_track(self) -> list[GPSPoint]:
        root = self.etree.getroot()
        if root is None:
            raise ValueError("ElementTree root is None")

        for track_id in range(1, MAX_TRACK_ID + 1):
            track_ns = f"Track{track_id}"
            if self._all_tags_exists(
                {
                    expand_tag(f"{track_ns}:SampleTime"),
                    expand_tag(f"{track_ns}:SampleDuration"),
                    expand_tag(f"{track_ns}:GPSLongitude"),
                    expand_tag(f"{track_ns}:GPSLatitude"),
                }
            ):
                sample_iterator = _aggregate_samples(
                    root,
                    f"{track_ns}:SampleTime",
                    f"{track_ns}:SampleDuration",
                )
                track = _aggregate_gps_track_by_sample_time(
                    sample_iterator,
                    lon_tag=f"{track_ns}:GPSLongitude",
                    lat_tag=f"{track_ns}:GPSLatitude",
                    alt_tag=f"{track_ns}:GPSAltitude",
                    direction_tag=f"{track_ns}:GPSTrack",
                    ground_speed_tag=f"{track_ns}:GPSSpeed",
                    gps_fix_tag=f"{track_ns}:GPSMeasureMode",
                    gps_precision_tag=f"{track_ns}:GPSHPositioningError",
                )
                if track:
                    return track
        return []

    def _extract_alternative_fields(
        self,
        fields: T.Sequence[str],
        field_type: T.Type[_FIELD_TYPE],
    ) -> _FIELD_TYPE | None:
        return _extract_alternative_fields(self._texts_by_tag, fields, field_type)

    def _all_tags_exists(self, tags: set[str]) -> bool:
        return self._all_tags.issuperset(tags)

    def _extract_gps_track_from_quicktime(
        self, namespace: str = "QuickTime"
    ) -> list[GPSPoint]:
        if not self._all_tags_exists(
            {
                expand_tag(f"{namespace}:GPSDateTime"),
                expand_tag(f"{namespace}:GPSLongitude"),
                expand_tag(f"{namespace}:GPSLatitude"),
            }
        ):
            return []

        return _aggregate_gps_track(
            self._texts_by_tag,
            time_tag=f"{namespace}:GPSDateTime",
            lon_tag=f"{namespace}:GPSLongitude",
            lat_tag=f"{namespace}:GPSLatitude",
            alt_tag=f"{namespace}:GPSAltitude",
            direction_tag=f"{namespace}:GPSTrack",
        )
