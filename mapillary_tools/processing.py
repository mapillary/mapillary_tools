from typing import Dict, List, Optional, Tuple, cast
import typing as T
import datetime
import os
from collections import OrderedDict
import logging

from tqdm import tqdm

from . import image_log
from . import types
from .error import MapillaryGeoTaggingError, MapillaryInterpolationError
from .exif_read import ExifRead
from .exif_write import ExifEdit
from .geo import normalize_bearing, interpolate_lat_lon
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
    for image in tqdm(
        process_file_list, unit="files", desc="Extracting GPS data from image EXIF"
    ):

        try:
            point = gpx_from_exif(image)
        except MapillaryGeoTaggingError as ex:
            image_log.create_and_log_process_in_memory(
                image,
                "geotag_process",
                "failed",
                {
                    "process": "geotag_process",
                    "message": str(ex),
                },
            )
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

        image_log.create_and_log_process_in_memory(
            image,
            "geotag_process",
            "success",
            point.as_desc(),
        )


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
    local_time: bool,
    use_gps_start_time=False,
) -> None:
    if not os.path.isdir(geotag_source_path):
        raise RuntimeError(
            f"The path specified in geotag_source_path {geotag_source_path} is not a directory"
        )

    gopro_videos = image_log.get_video_file_list(geotag_source_path)
    for gopro_video in gopro_videos:
        trace = gpx_from_gopro(gopro_video)
        _geotag_from_gpx(
            _filter_video_samples(process_file_list, gopro_video),
            trace,
            offset_time,
            offset_angle,
            local_time,
            use_gps_start_time,
        )


def _geotag_from_gpx(
    images: List[str],
    points: List[types.GPXPoint],
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
    local_time: bool = False,
    use_gps_start_time: bool = False,
):
    # need EXIF timestamps for sorting
    pairs = [(ExifRead(f).extract_capture_time(), f) for f in images]

    if use_gps_start_time:
        filtered_pairs: List[Tuple[datetime.datetime, str]] = [
            T.cast(Tuple[datetime.datetime, str], p) for p in pairs if p[0] is not None
        ]
        sorted_pairs = sorted(filtered_pairs)
        if sorted_pairs:
            # assume: the ordered image timestamps are [2, 3, 4, 5]
            # the ordered gpx timestamps are [5, 6, 7, 8]
            # then the exif_time_offset will be 5 - 2 = 3
            first_exif_time = sorted_pairs[0][0]
            offset_time = (points[0].time - first_exif_time).total_seconds()

    for exif_time, image in pairs:
        if exif_time is None:
            image_log.create_and_log_process_in_memory(
                image,
                "geotag_process",
                "failed",
                {
                    "process": "geotag_process",
                    "message": "Unable to extract the timestamp",
                },
            )
        else:
            corrected_exif_time = exif_time + datetime.timedelta(seconds=offset_time)
            try:
                lat, lon, bearing, elevation = interpolate_lat_lon(
                    points, corrected_exif_time
                )
            except MapillaryInterpolationError as ex:
                raise RuntimeError(
                    f"""Failed to interpolate image {image} with the geotag source. Try the following fixes:
1. Specify --local_time to read the timestamps from the geotag source file as local time
2. Use --use_gps_start_time
3. Add a time offset with --offset_time to your image timestamps
"""
                ) from ex

            corrected_angle = normalize_bearing(bearing + offset_angle)
            point = types.GPXPointAngle(
                point=types.GPXPoint(
                    time=corrected_exif_time,
                    lon=lon,
                    lat=lat,
                    alt=elevation,
                ),
                angle=corrected_angle,
            )
            image_log.create_and_log_process_in_memory(
                image, "geotag_process", "success", point.as_desc()
            )


def geotag_from_blackvue_video(
    process_file_list: T.List[str],
    geotag_source_path: str,
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
    local_time: bool = False,
    use_gps_start_time=False,
) -> None:
    if not os.path.isdir(geotag_source_path):
        raise RuntimeError(
            f"The path specified in --geotag_source_path {geotag_source_path} is not a directory"
        )

    blackvue_videos = image_log.get_video_file_list(geotag_source_path)
    for blackvue_video in blackvue_videos:
        process_file_sublist = _filter_video_samples(process_file_list, blackvue_video)
        if not process_file_sublist:
            continue

        [points, is_stationary_video] = gpx_from_blackvue(
            blackvue_video, use_nmea_stream_timestamp=False
        )

        if not points:
            LOG.warning(
                f"Skipping the BlackVue video {blackvue_video} -- no GPS information found in the video"
            )
            for image in process_file_sublist:
                image_log.create_and_log_process_in_memory(
                    image,
                    "geotag_process",
                    "failed",
                    {
                        "process": "geotag_process",
                        "code": "no_gps_found",
                        "message": f"no GPS information found in the blackvue video {blackvue_video}",
                    },
                )
            continue

        if is_stationary_video:
            LOG.warning(f"Skipping stationary BlackVue video {blackvue_video}")
            for image in process_file_sublist:
                image_log.create_and_log_process_in_memory(
                    image,
                    "geotag_process",
                    "failed",
                    {
                        "process": "geotag_process",
                        "code": "stationary_blackvue",
                        "message": f"unable to geotag from a stationary blackvue",
                    },
                )
            continue

        _geotag_from_gpx(
            process_file_sublist,
            points,
            offset_time,
            offset_angle,
            local_time,
            use_gps_start_time,
        )


def geotag_from_nmea_file(
    process_file_list: T.List[str],
    geotag_source_path: str,
    offset_time=0.0,
    offset_angle=0.0,
    local_time=False,
    use_gps_start_time=False,
) -> None:
    if not os.path.isfile(geotag_source_path):
        raise RuntimeError(
            f"geotag_source_path {geotag_source_path} is not a NMEA file"
        )

    if not process_file_list:
        return

    gps_trace = get_lat_lon_time_from_nmea(geotag_source_path)

    if not gps_trace:
        LOG.warning(
            f"NMEA trace file {geotag_source_path} was not read, images can not be geotagged."
        )
        for image in process_file_list:
            image_log.create_and_log_process_in_memory(
                image,
                "geotag_process",
                "failed",
                {
                    "process": "geotag_process",
                    "message": "Not GPS trace found in the NMEA file",
                },
            )
        return

    _geotag_from_gpx(
        process_file_list,
        gps_trace,
        offset_time,
        offset_angle,
        local_time,
        use_gps_start_time,
    )


def geotag_from_gpx_file(
    process_file_list: T.List[str],
    geotag_source_path: str,
    offset_time=0.0,
    offset_angle=0.0,
    local_time=False,
    use_gps_start_time=False,
) -> None:
    if not os.path.isfile(geotag_source_path):
        raise RuntimeError(
            f"The path specified in geotag_source_path {geotag_source_path} is not a GPX file"
        )

    if not process_file_list:
        return

    gps_trace = get_lat_lon_time_from_gpx(geotag_source_path)

    if not gps_trace:
        LOG.warning(
            f"Error, GPS trace file {geotag_source_path} was not read, images can not be geotagged."
        )
        return

    _geotag_from_gpx(
        process_file_list,
        gps_trace,
        offset_time,
        offset_angle,
        local_time,
        use_gps_start_time,
    )


def overwrite_exif_tags(
    image_path: str,
    final_mapillary_image_description: types.FinalImageDescription,
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
        image_exif.add_date_time_original(
            datetime.datetime.strptime(
                final_mapillary_image_description["MAPCaptureTime"],
                "%Y_%m_%d_%H_%M_%S_%f",
            )
        )
        modified = True

    if overwrite_all_EXIF_tags or overwrite_EXIF_gps_tag:
        image_exif.add_lat_lon(
            final_mapillary_image_description["MAPLatitude"],
            final_mapillary_image_description["MAPLongitude"],
        )
        modified = True

    if overwrite_all_EXIF_tags or overwrite_EXIF_direction_tag:
        image_exif.add_direction(
            final_mapillary_image_description["MAPCompassHeading"]["TrueHeading"]
        )
        modified = True

    if overwrite_all_EXIF_tags or overwrite_EXIF_orientation_tag:
        if "MAPOrientation" in final_mapillary_image_description:
            image_exif.add_orientation(
                final_mapillary_image_description["MAPOrientation"]
            )
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


def interpolate_timestamp(
    capture_times: List[datetime.datetime],
) -> List[datetime.datetime]:
    """
    Interpolate time stamps in case of identical timestamps
    """

    if len(capture_times) < 2:
        return capture_times

    # trace identical timestamps (always assume capture_times is sorted)
    time_dict: OrderedDict[datetime.datetime, Dict] = OrderedDict()
    for i, t in enumerate(capture_times):
        if t not in time_dict:
            time_dict[t] = {"count": 0, "pointer": 0}

            if 0 < i:
                interval = (t - capture_times[i - 1]).total_seconds()
                time_dict[capture_times[i - 1]]["interval"] = interval

        time_dict[t]["count"] += 1

    keys = list(time_dict.keys())
    if len(keys) >= 2:
        # set time interval as the last available time interval
        time_dict[keys[-1]]["interval"] = time_dict[keys[-2]]["interval"]
    else:
        # set time interval assuming capture interval is 1 second
        time_dict[keys[0]]["interval"] = time_dict[keys[0]]["count"] * 1.0

    timestamps = []

    # interpolate timestamps
    for t in capture_times:
        d = time_dict[t]
        s = datetime.timedelta(seconds=d["pointer"] * d["interval"] / float(d["count"]))
        updated_time = t + s
        time_dict[t]["pointer"] += 1
        timestamps.append(updated_time)

    return timestamps


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
