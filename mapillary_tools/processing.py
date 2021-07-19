from typing import Dict, List, Optional, Tuple, cast
import typing as T
import datetime
import json
import os
from collections import OrderedDict
import logging

from dateutil.tz import tzlocal
from tqdm import tqdm

from . import ipc, uploader, types
from .error import print_error, MapillaryGeoTaggingError, MapillaryInterpolationError
from .exif_read import ExifRead
from .exif_write import ExifEdit
from .geo import (
    normalize_bearing,
    interpolate_lat_lon,
    gps_distance,
)
from .gps_parser import get_lat_lon_time_from_gpx, get_lat_lon_time_from_nmea
from .gpx_from_blackvue import gpx_from_blackvue
from .gpx_from_exif import gpx_from_exif
from .gpx_from_gopro import gpx_from_gopro
from .utils import force_decode


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
        except MapillaryGeoTaggingError:
            create_and_log_process(image, "geotag_process", "failed", {}, verbose=False)
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

        create_and_log_process(
            image,
            "geotag_process",
            "success",
            point.as_desc(),
            verbose=False,
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

    gopro_videos = uploader.get_video_file_list(geotag_source_path)
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
    pairs = [(ExifRead(f).extract_capture_time(), f) for f in images]

    if use_gps_start_time:
        filtered_pairs: List[Tuple[datetime.datetime, str]] = [
            T.cast(Tuple[datetime.datetime, str], p) for p in pairs if p[0] is not None
        ]
        sorted_pairs = sorted(filtered_pairs)
        if sorted_pairs:
            # update offset time with the gps start time
            offset_time += (sorted_pairs[0][0] - points[0].time).total_seconds()
            LOG.info(
                f"Use GPS start time, which is same as using offset_time={offset_time}"
            )

    for capture_time, image in pairs:
        if capture_time is None:
            print_error(f"Error, capture time could not be extracted for image {image}")
            create_and_log_process(image, "geotag_process", "failed", {}, verbose=False)
        else:
            try:
                lat, lon, bearing, elevation = interpolate_lat_lon(points, capture_time)
            except MapillaryInterpolationError as ex:
                raise RuntimeError(
                    f"""Failed to interpolate image {image} with the geotag source. Try the following fixes:
1. Specify --local_time to read the timestamps from the geotag source file as local time
2. Use --use_gps_start_time to align the start time
3. Manually shift the timestamps in the geotag source file with --offset_time OFFSET_IN_SECONDS
"""
                ) from ex

            corrected_angle = normalize_bearing(bearing + offset_angle)
            corrected_timestamp = capture_time + datetime.timedelta(seconds=offset_time)
            point = types.GPXPointAngle(
                point=types.GPXPoint(
                    time=corrected_timestamp,
                    lon=lon,
                    lat=lat,
                    alt=elevation,
                ),
                angle=corrected_angle,
            )
            create_and_log_process(
                image, "geotag_process", "success", point.as_desc(), verbose=False
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

    blackvue_videos = uploader.get_video_file_list(geotag_source_path)
    for blackvue_video in blackvue_videos:
        process_file_sublist = _filter_video_samples(process_file_list, blackvue_video)
        if not process_file_sublist:
            continue

        [points, is_stationary_video] = gpx_from_blackvue(
            blackvue_video, use_nmea_stream_timestamp=False
        )

        if not points:
            LOG.warning(f"No GPX found in the BlackVue video {blackvue_video}")
            continue

        if is_stationary_video:
            LOG.warning(f"Skipping stationary BlackVue video {blackvue_video}")
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
            f"The path specified in geotag_source_path {geotag_source_path} is not a NMEA file"
        )

    gps_trace = get_lat_lon_time_from_nmea(geotag_source_path)

    if not gps_trace:
        print_error(
            f"Error, NMEA trace file {geotag_source_path} was not read, images can not be geotagged."
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

    gps_trace = get_lat_lon_time_from_gpx(geotag_source_path)

    if not gps_trace:
        print_error(
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


def read_process_data(image: str, process: types.Process) -> Optional[dict]:
    log_root = uploader.log_rootpath(image)
    path = os.path.join(log_root, f"{process}.json")
    if not os.path.isfile(path):
        return None
    return load_json(path)


def read_geotag_process_data(image: str) -> Optional[types.Image]:
    return cast(Optional[types.Image], read_process_data(image, "geotag_process"))


def read_sequence_process_data(image) -> Optional[types.Sequence]:
    return cast(Optional[types.Sequence], read_process_data(image, "sequence_process"))


def read_import_meta_data_process_data(image) -> Optional[types.MetaProperties]:
    return cast(
        Optional[types.MetaProperties],
        read_process_data(image, "import_meta_data_process"),
    )


def read_image_description(image) -> Optional[types.FinalImageDescription]:
    return cast(
        Optional[types.FinalImageDescription],
        read_process_data(image, "mapillary_image_description"),
    )


def get_final_mapillary_image_description(
    image: str,
) -> Optional[types.FinalImageDescription]:
    image_data = read_geotag_process_data(image)
    if image_data is None:
        return None

    sequence_data = read_sequence_process_data(image)
    if sequence_data is None:
        return None

    description: dict = {}

    description.update(cast(dict, image_data))
    description.update(cast(dict, sequence_data))

    meta = read_import_meta_data_process_data(image)
    if meta is not None:
        description.update(cast(dict, meta))

    # FIXME
    # description["MAPPhotoUUID"] = str(uuid.uuid4())

    return cast(types.FinalImageDescription, description)


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


def load_json(file_path: str):
    # FIXME: what if file_path does not exist
    with open(file_path) as fp:
        try:
            return json.load(fp)
        except json.JSONDecodeError:
            raise RuntimeError(f"Error JSON decoding {file_path}")


def save_json(data: T.Mapping, file_path: str) -> None:
    try:
        buf = json.dumps(data, indent=4)
    except Exception:
        # FIXME: more explicit
        raise RuntimeError(f"Error JSON serializing {data}")
    with open(file_path, "w") as f:
        f.write(buf)


def get_process_file_list(
    import_path: str,
    process: types.Process,
    rerun: bool = False,
    skip_subfolders: bool = False,
) -> List[str]:
    files = uploader.iterate_files(import_path, not skip_subfolders)
    sorted_files = sorted(
        file
        for file in files
        if uploader.is_image_file(file) and preform_process(file, process, rerun)
    )
    return sorted_files


def get_process_status_file_list(
    import_path: str,
    process: types.Process,
    status: types.Status,
    skip_subfolders: bool = False,
) -> List[str]:
    files = uploader.iterate_files(import_path, not skip_subfolders)
    return sorted(
        file
        for file in files
        if uploader.is_image_file(file) and process_status(file, process, status)
    )


def process_status(
    file_path: str, process: types.Process, status: types.Status
) -> bool:
    log_root = uploader.log_rootpath(file_path)
    if status == "success":
        status_file = os.path.join(log_root, process + ".json")
    elif status == "failed":
        status_file = os.path.join(log_root, process + ".error.json")
    else:
        raise ValueError(f"Invalid status {status}")
    return os.path.isfile(status_file)


def get_duplicate_file_list(
    import_path: str, skip_subfolders: bool = False
) -> List[str]:
    files = uploader.iterate_files(import_path, not skip_subfolders)
    return sorted(
        file for file in files if uploader.is_image_file(file) and is_duplicate(file)
    )


def is_duplicate(image: str) -> bool:
    log_root = uploader.log_rootpath(image)
    duplicate_flag_path = os.path.join(log_root, "duplicate")
    return os.path.isfile(duplicate_flag_path)


def mark_as_duplicated(image: str) -> None:
    log_root = uploader.log_rootpath(image)
    duplicate_flag_path = os.path.join(log_root, "duplicate")
    open(duplicate_flag_path, "w").close()


def unmark_duplicated(image: str) -> None:
    log_root = uploader.log_rootpath(image)
    duplicate_flag_path = os.path.join(log_root, "duplicate")
    if os.path.isfile(duplicate_flag_path):
        os.remove(duplicate_flag_path)


def preform_process(
    file_path: str, process: types.Process, rerun: bool = False
) -> bool:
    log_root = uploader.log_rootpath(file_path)
    process_success = os.path.join(log_root, process + ".json")
    preform = not os.path.isfile(process_success) or rerun
    return preform


def processed_images_rootpath(filepath: str) -> str:
    return os.path.join(
        os.path.dirname(filepath),
        ".mapillary",
        "processed_images",
        os.path.basename(filepath),
    )


def create_and_log_process(
    image: str,
    process: types.Process,
    status: types.Status,
    description: T.Mapping,
    verbose: bool = False,
) -> None:
    log_root = uploader.log_rootpath(image)
    if not os.path.isdir(log_root):
        os.makedirs(log_root)

    log_MAPJson = os.path.join(log_root, process + ".json")
    log_MAPJson_failed = os.path.join(log_root, process + ".error.json")

    if status == "success":
        save_json(description, log_MAPJson)
        if os.path.isfile(log_MAPJson_failed):
            os.remove(log_MAPJson_failed)
    elif status == "failed":
        save_json(description, log_MAPJson_failed)
        if os.path.isfile(log_MAPJson):
            os.remove(log_MAPJson)
    else:
        raise ValueError(f"Invalid status {status}")

    decoded_image = force_decode(image)

    ipc.send(
        process,
        {
            "image": decoded_image,
            "status": status,
            "description": description,
        },
    )


def load_geotag_points(
    process_file_list: List[str], verbose: bool = False
) -> Tuple[List[str], List[datetime.datetime], List[float], List[float], List[float]]:
    file_list = []
    capture_times = []
    lats = []
    lons = []
    directions = []

    for image in process_file_list:
        geotag_data = read_geotag_process_data(image)
        if geotag_data is None:
            create_and_log_process(
                image, "sequence_process", "failed", {}, verbose=verbose
            )
            continue

        # assume all data needed available from this point on
        file_list.append(image)
        capture_times.append(
            datetime.datetime.strptime(
                geotag_data["MAPCaptureTime"], "%Y_%m_%d_%H_%M_%S_%f"
            )
        )
        lats.append(geotag_data["MAPLatitude"])
        lons.append(geotag_data["MAPLongitude"])
        directions.append(
            geotag_data["MAPCompassHeading"]["TrueHeading"]
        ) if "MAPCompassHeading" in geotag_data else directions.append(0.0)

        unmark_duplicated(image)

    return file_list, capture_times, lats, lons, directions


def split_sequences(
    capture_times: List[datetime.datetime],
    lats: List[float],
    lons: List[float],
    file_list: List[str],
    directions: List[float],
    cutoff_time: float,
    cutoff_distance: float,
    verbose: bool = False,
) -> List[Dict]:
    sequences: List[Dict] = []
    # sort based on time
    sort_by_time = list(zip(capture_times, file_list, lats, lons, directions))
    sort_by_time.sort()
    capture_times, file_list, lats, lons, directions = [
        list(x) for x in zip(*sort_by_time)
    ]
    latlons = list(zip(lats, lons))

    # initialize first sequence
    sequence_index = 0
    sequences.append(
        {
            "file_list": [file_list[0]],
            "directions": [directions[0]],
            "latlons": [latlons[0]],
            "capture_times": [capture_times[0]],
        }
    )

    if len(file_list) >= 1:
        # diff in capture time
        capture_deltas = [t2 - t1 for t1, t2 in zip(capture_times, capture_times[1:])]

        # distance between consecutive images
        distances = [gps_distance(ll1, ll2) for ll1, ll2 in zip(latlons, latlons[1:])]

        # if cutoff time is given use that, else assume cutoff is
        # 1.5x median time delta
        if cutoff_time is None:
            if verbose:
                print(
                    "Warning, sequence cut-off time is None and will therefore be derived based on the median time delta between the consecutive images."
                )
            median = sorted(capture_deltas)[len(capture_deltas) // 2]
            if type(median) is not int:
                median = median.total_seconds()
            cutoff_time = 1.5 * median
        else:
            cutoff_time = float(cutoff_time)
        cut = 0
        for i, filepath in enumerate(file_list[1:]):
            cut_time = capture_deltas[i].total_seconds() > cutoff_time
            cut_distance = distances[i] > cutoff_distance
            if cut_time or cut_distance:
                cut += 1
                # delta too big, start new sequence
                sequence_index += 1
                sequences.append(
                    {
                        "file_list": [filepath],
                        "directions": [directions[1:][i]],
                        "latlons": [latlons[1:][i]],
                        "capture_times": [capture_times[1:][i]],
                    }
                )
                if verbose:
                    if cut_distance:
                        print(
                            f"Cut {cut}: Delta in distance {distances[i]} meters is bigger than cutoff_distance {cutoff_distance} meters at {file_list[i + 1]}"
                        )
                    elif cut_time:
                        print(
                            f"Cut {cut}: Delta in time {capture_deltas[i].total_seconds()} seconds is bigger then cutoff_time {cutoff_time} seconds at {file_list[i + 1]}"
                        )
            else:
                # delta not too big, continue with current
                # group
                sequences[sequence_index]["file_list"].append(filepath)
                sequences[sequence_index]["directions"].append(directions[1:][i])
                sequences[sequence_index]["latlons"].append(latlons[1:][i])
                sequences[sequence_index]["capture_times"].append(capture_times[1:][i])

    return sequences


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
