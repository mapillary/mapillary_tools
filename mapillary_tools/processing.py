from typing import Dict, List, Tuple
import typing as T
import datetime
import os
import logging

from tqdm import tqdm

from . import image_log
from . import types
from .error import MapillaryGeoTaggingError, MapillaryStationaryBlackVueError
from .exif_read import ExifRead
from .exif_write import ExifEdit
from .geo import normalize_bearing, interpolate_lat_lon, Point
from .gps_parser import get_lat_lon_time_from_gpx, get_lat_lon_time_from_nmea
from .gpx_from_blackvue import gpx_from_blackvue
from .gpx_from_exif import gpx_from_exif
from .gpx_from_gopro import gpx_from_gopro

LOG = logging.getLogger()


def geotag_from_exif(
    process_file_list: List[str],
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
) -> None:
    for image in tqdm(process_file_list, unit="files", desc="Extracting GPS from EXIF"):

        try:
            point = gpx_from_exif(image)
        except MapillaryGeoTaggingError as ex:
            image_log.log_failed_in_memory(image, "geotag_process", ex)
            continue

        corrected_time = point.point.time + datetime.timedelta(seconds=offset_time)

        if point.angle is not None:
            corrected_angle: T.Optional[float] = normalize_bearing(
                point.angle + offset_angle
            )
        else:
            corrected_angle = None

        point = types.GPXPointAngle(
            point=types.GPXPoint(
                time=corrected_time,
                lon=point.point.lon,
                lat=point.point.lat,
                alt=point.point.alt,
            ),
            angle=corrected_angle,
        )

        image_log.log_in_memory(image, "geotag_process", point.as_desc())


def video_sample_path(import_path: str, video_file_path: str) -> str:
    video_filename = os.path.basename(video_file_path)
    return os.path.join(import_path, video_filename)


def is_sample_of_video(sample_path: str, video_filename: str) -> bool:
    abs_sample_path = os.path.abspath(sample_path)
    video_basename = os.path.basename(video_filename)
    if video_basename == os.path.basename(os.path.dirname(abs_sample_path)):
        sample_basename = os.path.basename(sample_path)
        root, _ = os.path.splitext(video_basename)
        return sample_basename.startswith(root + "_")
    return False


def _filter_video_samples(images: T.List[str], video_path: str) -> T.List[str]:
    return [image for image in images if is_sample_of_video(image, video_path)]


def geotag_from_gopro_video(
    process_file_list: T.List[str],
    geotag_source_path: str,
    offset_time: float,
    offset_angle: float,
) -> None:
    if os.path.isdir(geotag_source_path):
        gopro_videos = image_log.get_video_file_list(geotag_source_path)
        for gopro_video in gopro_videos:
            trace = gpx_from_gopro(gopro_video)
            _geotag_from_gpx(
                _filter_video_samples(process_file_list, gopro_video),
                trace,
                offset_time,
                offset_angle,
            )
    elif os.path.isfile(geotag_source_path):
        trace = gpx_from_gopro(geotag_source_path)
        _geotag_from_gpx(
            _filter_video_samples(process_file_list, geotag_source_path),
            trace,
            offset_time,
            offset_angle,
        )
    else:
        raise RuntimeError(
            f"The geotag_source_path {geotag_source_path} does not exist"
        )


def _geotag_from_gpx(
    images: List[str],
    points: List[types.GPXPoint],
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
    read_image_time: T.Optional[T.Callable] = None,
):
    if read_image_time is None:
        read_image_time = lambda img: ExifRead(img).extract_capture_time()

    if not points:
        raise ValueError("Empty GPX list provided")

    # need EXIF timestamps for sorting
    pairs = []
    for image in images:
        capture_time = read_image_time(image)
        if capture_time is None:
            image_log.log_failed_in_memory(
                image,
                "geotag_process",
                MapillaryGeoTaggingError("No capture time found in EXIF"),
            )
        else:
            pairs.append((capture_time, image))

    sorted_points = sorted(points, key=lambda p: p.time)
    sorted_pairs = sorted(pairs)

    if sorted_pairs:
        # assume: the ordered image timestamps are [2, 3, 4, 5]
        # the ordered gpx timestamps are [5, 6, 7, 8]
        # then the offset will be 5 - 2 = 3
        time_delta = (sorted_points[0].time - sorted_pairs[0][0]).total_seconds()
    else:
        time_delta = 0.0

    # same thing but different type
    sorted_points_for_interpolation = [
        Point(lat=p.lat, lon=p.lon, alt=p.alt, time=p.time) for p in sorted_points
    ]

    for exif_time, image in sorted_pairs:
        exif_time = exif_time + datetime.timedelta(seconds=time_delta)
        lat, lon, bearing, elevation = interpolate_lat_lon(
            sorted_points_for_interpolation, exif_time
        )

        corrected_angle = normalize_bearing(bearing + offset_angle)
        corrected_time = exif_time + datetime.timedelta(seconds=offset_time)
        point = types.GPXPointAngle(
            point=types.GPXPoint(
                time=corrected_time,
                lon=lon,
                lat=lat,
                alt=elevation,
            ),
            angle=corrected_angle,
        )
        image_log.log_in_memory(image, "geotag_process", point.as_desc())


def geotag_from_blackvue_video(
    process_file_list: T.List[str],
    geotag_source_path: str,
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
) -> None:
    if os.path.isdir(geotag_source_path):
        blackvue_videos = image_log.get_video_file_list(geotag_source_path)
    elif os.path.isfile(geotag_source_path):
        blackvue_videos = [geotag_source_path]
    else:
        raise RuntimeError(
            f"The geotag_source_path {geotag_source_path} does not exist"
        )

    for blackvue_video in blackvue_videos:
        process_file_sublist = _filter_video_samples(process_file_list, blackvue_video)
        if not process_file_sublist:
            continue

        [points, is_stationary_video] = gpx_from_blackvue(
            blackvue_video, use_nmea_stream_timestamp=False
        )

        if not points:
            message = f"Skipping the BlackVue video {blackvue_video} -- no GPS found in the video"
            for image in process_file_sublist:
                image_log.log_failed_in_memory(
                    image,
                    "geotag_process",
                    MapillaryGeoTaggingError(message),
                )
            continue

        if is_stationary_video:
            message = f"Skipping stationary BlackVue video {blackvue_video}"
            for image in process_file_sublist:
                image_log.log_failed_in_memory(
                    image,
                    "geotag_process",
                    MapillaryStationaryBlackVueError(message),
                )
            continue

        _geotag_from_gpx(
            process_file_sublist,
            points,
            offset_time,
            offset_angle,
        )


def geotag_from_nmea_file(
    process_file_list: T.List[str],
    geotag_source_path: str,
    offset_time=0.0,
    offset_angle=0.0,
) -> None:
    if not os.path.isfile(geotag_source_path):
        raise RuntimeError(
            f"geotag_source_path {geotag_source_path} is not a NMEA file"
        )

    if not process_file_list:
        return

    gps_trace = get_lat_lon_time_from_nmea(geotag_source_path)

    if not gps_trace:
        message = f"No GPS extracted from the NMEA trace file {geotag_source_path}"
        LOG.warning(message)
        for image in process_file_list:
            image_log.log_failed_in_memory(
                image,
                "geotag_process",
                MapillaryGeoTaggingError(message),
            )
        return

    _geotag_from_gpx(
        process_file_list,
        gps_trace,
        offset_time,
        offset_angle,
    )


def geotag_from_gpx_file(
    process_file_list: T.List[str],
    geotag_source_path: str,
    offset_time=0.0,
    offset_angle=0.0,
) -> None:
    if not os.path.isfile(geotag_source_path):
        raise RuntimeError(
            f"The path specified in geotag_source_path {geotag_source_path} is not a GPX file"
        )

    if not process_file_list:
        return

    gps_trace = get_lat_lon_time_from_gpx(geotag_source_path)

    if not gps_trace:
        message = f"No GPS extracted from the GPX file {geotag_source_path}"
        for image in process_file_list:
            image_log.log_failed_in_memory(
                image,
                "geotag_process",
                MapillaryGeoTaggingError(message),
            )
        return

    _geotag_from_gpx(
        process_file_list,
        gps_trace,
        offset_time,
        offset_angle,
    )


def overwrite_exif_tags(
    image_path: str,
    desc: types.FinalImageDescription,
    overwrite_all_EXIF_tags: bool = False,
    overwrite_EXIF_time_tag: bool = False,
    overwrite_EXIF_gps_tag: bool = False,
    overwrite_EXIF_direction_tag: bool = False,
    overwrite_EXIF_orientation_tag: bool = False,
) -> None:
    modified = False

    image_exif = ExifEdit(image_path)

    # also try to set time and gps so image can be placed on the map for testing and
    # qc purposes
    if overwrite_all_EXIF_tags or overwrite_EXIF_time_tag:
        dt = types.map_capture_time_to_datetime(desc["MAPCaptureTime"])
        image_exif.add_date_time_original(dt)
        modified = True

    if overwrite_all_EXIF_tags or overwrite_EXIF_gps_tag:
        image_exif.add_lat_lon(
            desc["MAPLatitude"],
            desc["MAPLongitude"],
        )
        modified = True

    if overwrite_all_EXIF_tags or overwrite_EXIF_direction_tag:
        heading = desc.get("MAPCompassHeading")
        if heading is not None:
            image_exif.add_direction(heading["TrueHeading"])
            modified = True

    if overwrite_all_EXIF_tags or overwrite_EXIF_orientation_tag:
        if "MAPOrientation" in desc:
            image_exif.add_orientation(desc["MAPOrientation"])
            modified = True

    if modified:
        image_exif.write()


def format_orientation(orientation: int) -> int:
    """
    Convert orientation from clockwise degrees to exif tag

    # see http://sylvana.net/jpegcrop/exif_orientation.html
    """
    mapping: T.Mapping[int, int] = {
        0: 1,
        90: 8,
        180: 3,
        270: 6,
    }
    if orientation not in mapping:
        raise ValueError("Orientation value has to be 0, 90, 180, or 270")

    return mapping[orientation]


def get_images_geotags(process_file_list: List[str]):
    geotags = []
    missing_geotags = []
    for image in tqdm(sorted(process_file_list), desc="Reading GPS data"):
        exif = ExifRead(image)
        timestamp = exif.extract_capture_time()
        lon, lat = exif.extract_lon_lat()
        altitude = exif.extract_altitude()
        if timestamp and lon and lat:
            geotags.append((timestamp, lat, lon, altitude))
            continue
        if timestamp and (not lon or not lat):
            missing_geotags.append((image, timestamp))
    return geotags, missing_geotags
