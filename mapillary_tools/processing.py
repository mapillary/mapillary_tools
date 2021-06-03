import base64
from typing import Any, Dict, List, Optional, Tuple, Union

import datetime
import hashlib
import json
import os
import time
import uuid
from collections import OrderedDict

from dateutil.tz import tzlocal
from tqdm import tqdm

from . import api_v3
from . import ipc
from . import uploader
from .error import print_error
from .exif_read import ExifRead
from .exif_write import ExifEdit
from .geo import normalize_bearing, interpolate_lat_lon, gps_distance
from .gps_parser import get_lat_lon_time_from_gpx, get_lat_lon_time_from_nmea
from .gpx_from_blackvue import gpx_from_blackvue
from .gpx_from_exif import gpx_from_exif
from .gpx_from_gopro import gpx_from_gopro
from .utils import force_decode

"""
auxillary processing functions
"""


def exif_time(filename):
    """
    Get image capture time from exif
    """
    metadata = ExifRead(filename)
    return metadata.extract_capture_time()


def estimate_sub_second_time(files, interval=0.0):
    """
    Estimate the capture time of a sequence with sub-second precision
    EXIF times are only given up to a second of precision. This function
    uses the given interval between shots to estimate the time inside that
    second that each picture was taken.
    """
    if interval <= 0.0:
        return [exif_time(f) for f in tqdm(files, desc="Reading image capture time")]

    onesecond = datetime.timedelta(seconds=1.0)
    T = datetime.timedelta(seconds=interval)
    for i, f in tqdm(enumerate(files), desc="Estimating subsecond time"):
        m = exif_time(f)
        if not m:
            pass
        if i == 0:
            smin = m
            smax = m + onesecond
        else:
            m0 = m - T * i
            smin = max(smin, m0)
            smax = min(smax, m0 + onesecond)
    if not smin or not smax:
        return None
    if smin > smax:
        # ERROR LOG
        print("Interval not compatible with EXIF times")
        return None
    else:
        s = smin + (smax - smin) / 2
        return [s + T * i for i in range(len(files))]


def geotag_from_exif(
    process_file_list: List[str],
    import_path: str,
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
    verbose: bool = False,
) -> None:
    if offset_time == 0:
        for image in tqdm(
            process_file_list, desc="Extracting gps data from image EXIF"
        ):
            geotag_properties = get_geotag_properties_from_exif(
                image, offset_angle, verbose
            )

            create_and_log_process(
                image, "geotag_process", "success", geotag_properties, verbose
            )
    else:
        try:
            geotag_source_path = gpx_from_exif(process_file_list, import_path, verbose)
            if not geotag_source_path or not os.path.isfile(geotag_source_path):
                raise Exception
        except Exception as e:
            print_error(
                f"Error, failed extracting data from exif due to {e}, exiting..."
            )
            raise e

        geotag_from_gps_trace(
            process_file_list,
            "gpx",
            geotag_source_path,
            offset_time,
            offset_angle,
            verbose=verbose,
        )


def get_geotag_properties_from_exif(
    image: str, offset_angle: float = 0.0, verbose: bool = False
) -> Optional[Dict]:
    try:
        exif = ExifRead(image)
    except:
        print_error(
            "Error, EXIF could not be read for image "
            + image
            + ", geotagging process failed for this image since gps/time properties not read."
        )
        return None
    # required tags
    try:
        lon, lat = exif.extract_lon_lat()
    except:
        print_error(
            "Error, "
            + image
            + " image latitude or longitude tag not in EXIF. Geotagging process failed for this image, since this is required information."
        )
        return None
    if lat is not None and lon is not None:
        geotag_properties: Dict = {
            "MAPLatitude": lat,
            "MAPLongitude": lon,
        }
    else:
        print_error(
            "Error, "
            + image
            + " image latitude or longitude tag not in EXIF. Geotagging process failed for this image, since this is required information."
        )
        return None
    try:
        timestamp = exif.extract_capture_time()
        if timestamp is None:
            raise Exception
    except:
        print_error(
            "Error, "
            + image
            + " image capture time tag not in EXIF. Geotagging process failed for this image, since this is required information."
        )
        return None

    try:
        geotag_properties["MAPCaptureTime"] = datetime.datetime.strftime(
            timestamp, "%Y_%m_%d_%H_%M_%S_%f"
        )[:-3]
    except:
        print_error(
            f"Error, {image} image capture time tag incorrect format. Geotagging process failed for this image, since this is required information."
        )
        return None

    # optional fields
    try:
        geotag_properties["MAPAltitude"] = exif.extract_altitude()
    except:
        if verbose:
            print("Warning, image altitude tag not in EXIF.")
    try:
        heading = exif.extract_direction()
        if heading is None:
            heading = 0.0
        heading = normalize_bearing(heading + offset_angle)
        # bearing of the image
        geotag_properties["MAPCompassHeading"] = {
            "TrueHeading": heading,
            "MagneticHeading": heading,
        }
    except:
        if verbose:
            print("Warning, image direction tag not in EXIF.")

    return geotag_properties


def geotag_from_gopro_video(
    process_file_list,
    import_path,
    geotag_source_path,
    offset_time,
    offset_angle,
    local_time,
    sub_second_interval,
    use_gps_start_time=False,
    verbose=False,
):
    # for each video, create gpx trace and geotag the corresponding video
    # frames
    gopro_videos = uploader.get_video_file_list(geotag_source_path)
    for gopro_video in gopro_videos:
        gopro_video_filename = (
            os.path.basename(gopro_video).replace(".mp4", "").replace(".MP4", "")
        )
        try:
            gpx_path = gpx_from_gopro(gopro_video)
            if not gpx_path or not os.path.isfile(gpx_path):
                raise Exception
        except Exception as e:
            print_error(
                f"Error, failed extracting data from gopro geotag source path {gopro_video} due to {e}, exiting..."
            )
            continue

        process_file_sublist = [
            x
            for x in process_file_list
            if os.path.join(gopro_video_filename, gopro_video_filename + "_") in x
        ]

        if not len(process_file_sublist):
            print_error(
                f"Error, no video frames extracted for video file {gopro_video} in import_path {import_path}"
            )
            create_and_log_process_in_list(
                process_file_sublist, "geotag_process", "failed", verbose=verbose
            )
            continue

        geotag_from_gps_trace(
            process_file_sublist,
            "gpx",
            gpx_path,
            offset_time,
            offset_angle,
            local_time,
            sub_second_interval,
            use_gps_start_time,
            verbose,
        )


def geotag_from_blackvue_video(
    process_file_list,
    import_path,
    geotag_source_path,
    offset_time,
    offset_angle,
    local_time,
    sub_second_interval,
    use_gps_start_time=False,
    verbose=False,
):
    # for each video, create gpx trace and geotag the corresponding video
    # frames
    blackvue_videos = uploader.get_video_file_list(geotag_source_path)
    for blackvue_video in blackvue_videos:
        blackvue_video_filename = (
            os.path.basename(blackvue_video).replace(".mp4", "").replace(".MP4", "")
        )
        [gpx_path, is_stationary_video] = gpx_from_blackvue(
            blackvue_video, use_nmea_stream_timestamp=False
        )

        if not gpx_path or not os.path.isfile(gpx_path):
            raise RuntimeError(f"Error, GPX path {gpx_path} not found")

        if is_stationary_video:
            print_error("Warning: Skipping stationary video")
            continue

        process_file_sublist = [
            x
            for x in process_file_list
            if os.path.join(blackvue_video_filename, blackvue_video_filename + "_") in x
        ]

        if not len(process_file_sublist):
            print_error(
                f"Error, no video frames extracted for video file {blackvue_video} in import_path {import_path}"
            )
            create_and_log_process_in_list(
                process_file_sublist, "geotag_process", "failed", verbose=verbose
            )
            continue

        geotag_from_gps_trace(
            process_file_sublist,
            "gpx",
            gpx_path,
            offset_time,
            offset_angle,
            local_time,
            sub_second_interval,
            use_gps_start_time,
            verbose,
        )


def geotag_from_gps_trace(
    process_file_list,
    geotag_source,
    geotag_source_path,
    offset_time=0.0,
    offset_angle=0.0,
    local_time=False,
    sub_second_interval=0.0,
    use_gps_start_time=False,
    verbose=False,
):
    # print time now to warn in case local_time
    if local_time:
        now = datetime.datetime.now(tzlocal())
        print(
            f"Your local timezone is {now.strftime('%Y-%m-%d %H:%M:%S %Z')}. If not, the geotags will be wrong."
        )
    else:
        # if not local time to be used, warn UTC will be used
        print(
            "It is assumed that the image timestamps are in UTC. If not, try using the option --local_time."
        )

    # read gps file to get track locations
    if geotag_source == "gpx":
        gps_trace = get_lat_lon_time_from_gpx(geotag_source_path, local_time)
    elif geotag_source == "nmea":
        gps_trace = get_lat_lon_time_from_nmea(geotag_source_path, local_time)
    else:
        raise RuntimeError(f"Invalid geotag source {geotag_source}")

    # Estimate capture time with sub-second precision, reading from image EXIF
    sub_second_times = estimate_sub_second_time(process_file_list, sub_second_interval)
    if not sub_second_times:
        print_error(
            "Error, capture times could not be estimated to sub second precision, images can not be geotagged."
        )
        create_and_log_process_in_list(
            process_file_list, "geotag_process", "failed", verbose=verbose
        )
        return

    if not gps_trace:
        print_error(
            f"Error, gps trace file {geotag_source_path} was not read, images can not be geotagged."
        )
        create_and_log_process_in_list(
            process_file_list, "geotag_process", "failed", verbose=verbose
        )
        return

    if use_gps_start_time:
        # update offset time with the gps start time
        offset_time += (sorted(sub_second_times)[0] - gps_trace[0][0]).total_seconds()
    for image, capture_time in tqdm(
        zip(process_file_list, sub_second_times),
        desc="Inserting gps data into image EXIF",
    ):
        if not capture_time:
            print_error("Error, capture time could not be extracted for image " + image)
            create_and_log_process(image, "geotag_process", "failed", verbose=verbose)
            continue

        geotag_properties = get_geotag_properties_from_gps_trace(
            image, capture_time, gps_trace, offset_angle, offset_time, verbose
        )

        create_and_log_process(
            image, "geotag_process", "success", geotag_properties, verbose
        )


def get_geotag_properties_from_gps_trace(
    image, capture_time, gps_trace, offset_angle=0.0, offset_time=0.0, verbose=False
):
    capture_time = capture_time - datetime.timedelta(seconds=offset_time)
    try:
        lat, lon, bearing, elevation = interpolate_lat_lon(gps_trace, capture_time)
    except Exception as e:
        print(
            f"Warning, {e}, interpolation of latitude and longitude failed for image {image}"
        )
        return None

    corrected_bearing = (bearing + offset_angle) % 360

    if lat is not None and lon is not None:
        geotag_properties = {
            "MAPLatitude": lat,
            "MAPLongitude": lon,
        }
    else:
        print(f"Warning, invalid latitude and longitude for image {image}")
        return None

    geotag_properties["MAPCaptureTime"] = datetime.datetime.strftime(
        capture_time, "%Y_%m_%d_%H_%M_%S_%f"
    )[:-3]
    if elevation:
        geotag_properties["MAPAltitude"] = elevation
    else:
        if verbose:
            print("Warning, image altitude tag not set.")
    if corrected_bearing:
        geotag_properties["MAPCompassHeading"] = {
            "TrueHeading": corrected_bearing,
            "MagneticHeading": corrected_bearing,
        }
    else:
        if verbose:
            print("Warning, image direction tag not set.")
    return geotag_properties


def get_upload_param_properties(
    log_root: str,
    image: str,
    user_name: str,
    user_upload_token: str,
    user_key: str,
    verbose: bool = False,
) -> Optional[Dict]:
    if not os.path.isdir(log_root):
        print(
            "Warning, sequence process has not been done for image "
            + image
            + ", therefore it will not be included in the upload params processing."
        )
        return None

    # check if geotag process was a success
    log_sequence_process_success = os.path.join(log_root, "sequence_process_success")
    if not os.path.isfile(log_sequence_process_success):
        print(
            "Warning, sequence process failed for image "
            + image
            + ", therefore it will not be included in the upload params processing."
        )
        return None

    upload_params_process_success_path = os.path.join(
        log_root, "upload_params_process_success"
    )

    # load the sequence json
    user_process_json_path = os.path.join(log_root, "user_process.json")
    try:
        user_data = load_json(user_process_json_path)
    except:
        print(
            f"Warning, user data not read for image {image}, therefore it will not be included in the upload params processing."
        )
        return None

    if "MAPSettingsUserKey" not in user_data:
        print(
            "Warning, user key not in user data for image {image}, therefore it will not be included in the upload params processing."
        )
        return None

    user_key = user_data["MAPSettingsUserKey"]
    organization_key = user_data.get("MAPOrganizationKey")
    private = user_data.get("MAPPrivate", False)

    # load the sequence json
    sequence_process_json_path = os.path.join(log_root, "sequence_process.json")
    try:
        sequence_data = load_json(sequence_process_json_path)
    except:
        print(
            "Warning, sequence data not read for image "
            + image
            + ", therefore it will not be included in the upload params processing."
        )
        return None

    if "MAPSequenceUUID" not in sequence_data:
        print(
            "Warning, sequence uuid not in sequence data for image "
            + image
            + ", therefore it will not be included in the upload params processing."
        )
        return None

    sequence_uuid = sequence_data["MAPSequenceUUID"]

    upload_params = {
        "key": sequence_uuid,
        "sequence_uuid": sequence_uuid,
        "user_key": user_key,
        "user_name": user_name,
        "organization_key": organization_key,
        "private": private,
    }

    x = base64.b64encode(image.encode("utf-8")).decode("utf-8")
    s = f"{user_upload_token}{user_key}{x}"
    settings_upload_hash = hashlib.sha256(s.encode("utf-8")).hexdigest()
    save_json(
        {"MAPSettingsUploadHash": settings_upload_hash},
        os.path.join(log_root, "settings_upload_hash.json"),
    )
    return upload_params


def get_final_mapillary_image_description(
    log_root: str,
    image: str,
    master_upload: bool = False,
    verbose: bool = False,
    skip_EXIF_insert: bool = False,
    keep_original: bool = False,
    overwrite_all_EXIF_tags: bool = False,
    overwrite_EXIF_time_tag: bool = False,
    overwrite_EXIF_gps_tag: bool = False,
    overwrite_EXIF_direction_tag: bool = False,
    overwrite_EXIF_orientation_tag: bool = False,
) -> Optional[Dict]:
    sub_commands = [
        "user_process",
        "geotag_process",
        "sequence_process",
        "upload_params_process",
        "settings_upload_hash",
        "import_meta_data_process",
    ]

    final_mapillary_image_description = {}
    for sub_command in sub_commands:
        sub_command_status = os.path.join(log_root, sub_command + "_failed")

        if (
            os.path.isfile(sub_command_status)
            and sub_command != "import_meta_data_process"
        ):
            print(f"Warning, required {sub_command} failed for image " + image)
            return None

        sub_command_data_path = os.path.join(log_root, sub_command + ".json")
        if (
            not os.path.isfile(sub_command_data_path)
            and sub_command != "import_meta_data_process"
        ):
            if (
                sub_command == "settings_upload_hash"
                or sub_command == "upload_params_process"
            ) and master_upload:
                continue
            else:
                print(
                    f"Warning, required {sub_command} did not result in a valid json file for image "
                    + image
                )
                return None
        if (
            sub_command == "settings_upload_hash"
            or sub_command == "upload_params_process"
        ):
            continue
        try:
            sub_command_data = load_json(sub_command_data_path)
            if not sub_command_data:
                if verbose:
                    print(
                        "Warning, no data read from json file " + sub_command_data_path
                    )
                return None

            final_mapillary_image_description.update(sub_command_data)
        except:
            if sub_command == "import_meta_data_process":
                if verbose:
                    print("Warning, could not load json file " + sub_command_data_path)
                continue
            else:
                if verbose:
                    print("Warning, could not load json file " + sub_command_data_path)
                return None

    # a unique photo ID to check for duplicates in the backend in case the
    # image gets uploaded more than once
    final_mapillary_image_description["MAPPhotoUUID"] = str(uuid.uuid4())

    if skip_EXIF_insert:
        return final_mapillary_image_description

    # insert in the EXIF image description
    try:
        image_exif = ExifEdit(image)
    except:
        print_error("Error, image EXIF could not be loaded for image " + image)
        return None
    try:
        image_exif.add_image_description(final_mapillary_image_description)
    except:
        print_error(
            "Error, image EXIF tag Image Description could not be edited for image "
            + image
        )
        return None
    # also try to set time and gps so image can be placed on the map for testing and
    # qc purposes
    if overwrite_all_EXIF_tags:
        try:
            image_exif.add_date_time_original(
                datetime.datetime.strptime(
                    final_mapillary_image_description["MAPCaptureTime"],
                    "%Y_%m_%d_%H_%M_%S_%f",
                )
            )
        except:
            pass
        try:
            image_exif.add_lat_lon(
                final_mapillary_image_description["MAPLatitude"],
                final_mapillary_image_description["MAPLongitude"],
            )
        except:
            pass
        try:
            image_exif.add_direction(
                final_mapillary_image_description["MAPCompassHeading"]["TrueHeading"]
            )
        except:
            pass
        try:
            if "MAPOrientation" in final_mapillary_image_description:
                image_exif.add_orientation(
                    final_mapillary_image_description["MAPOrientation"]
                )
        except:
            pass
    else:
        if overwrite_EXIF_time_tag:
            try:
                image_exif.add_date_time_original(
                    datetime.datetime.strptime(
                        final_mapillary_image_description["MAPCaptureTime"],
                        "%Y_%m_%d_%H_%M_%S_%f",
                    )
                )
            except:
                pass
        if overwrite_EXIF_gps_tag:
            try:
                image_exif.add_lat_lon(
                    final_mapillary_image_description["MAPLatitude"],
                    final_mapillary_image_description["MAPLongitude"],
                )
            except:
                pass
        if overwrite_EXIF_direction_tag:
            try:
                image_exif.add_direction(
                    final_mapillary_image_description["MAPCompassHeading"][
                        "TrueHeading"
                    ]
                )
            except:
                pass
        if overwrite_EXIF_orientation_tag:
            try:
                if "MAPOrientation" in final_mapillary_image_description:
                    image_exif.add_orientation(
                        final_mapillary_image_description["MAPOrientation"]
                    )
            except:
                pass
    filename = image
    filename_keep_original = processed_images_rootpath(image)
    if os.path.isfile(filename_keep_original):
        os.remove(filename_keep_original)
    if keep_original:
        filename = filename_keep_original
        if not os.path.isdir(os.path.dirname(filename_keep_original)):
            os.makedirs(os.path.dirname(filename_keep_original))
    try:
        image_exif.write(filename=filename)
    except:
        print_error("Error, image EXIF could not be written back for image " + image)
        return None

    return final_mapillary_image_description


def get_geotag_data(log_root: str, image: str, verbose: bool = False) -> Optional[Dict]:
    if not os.path.isdir(log_root):
        if verbose:
            print("Warning, no logs for image " + image)
        return None
    # check if geotag process was a success
    log_geotag_process_success = os.path.join(log_root, "geotag_process_success")
    if not os.path.isfile(log_geotag_process_success):
        print(
            "Warning, geotag process failed for image "
            + image
            + ", therefore it will not be included in the sequence processing."
        )
        return None
    # load the geotag json
    geotag_process_json_path = os.path.join(log_root, "geotag_process.json")
    try:
        geotag_data = load_json(geotag_process_json_path)
        return geotag_data
    except:
        if verbose:
            print(
                "Warning, geotag data not read for image "
                + image
                + ", therefore it will not be included in the sequence processing."
            )
        return None


def format_orientation(orientation):
    """
    Convert orientation from clockwise degrees to exif tag

    # see http://sylvana.net/jpegcrop/exif_orientation.html
    """
    mapping = {
        0: 1,
        90: 8,
        180: 3,
        270: 6,
    }
    if orientation not in mapping:
        raise ValueError("Orientation value has to be 0, 90, 180, or 270")

    return mapping[orientation]


def load_json(file_path: str):
    try:
        with open(file_path, "rb") as f:
            return json.load(f)
    except:
        return {}


def save_json(data: Dict[str, Any], file_path: str) -> None:
    try:
        buf = json.dumps(data, indent=4)
    except Exception:
        raise RuntimeError(f"Error JSON serializing {data}")
    with open(file_path, "w") as f:
        f.write(buf)


def update_json(data, file_path, process):
    original_data = load_json(file_path)
    original_data[process] = data
    save_json(original_data, file_path)


def get_process_file_list(
    import_path: str,
    process: str,
    rerun: bool = False,
    verbose: bool = False,
    skip_subfolders: bool = False,
    root_dir: Optional[str] = None,
) -> List[str]:
    if not root_dir:
        root_dir = import_path

    process_file_list: List[str] = []
    if skip_subfolders:
        process_file_list.extend(
            os.path.join(os.path.abspath(root_dir), file)
            for file in os.listdir(root_dir)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and preform_process(os.path.join(root_dir, file), process, rerun)
        )
    else:
        for root, dir, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            process_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if preform_process(os.path.join(root, file), process, rerun)
                and file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
            )

    inform_processing_start(root_dir, len(process_file_list), process)
    return sorted(process_file_list)


def get_process_status_file_list(
    import_path: str,
    process: str,
    status: str,
    skip_subfolders: bool = False,
    root_dir: Optional[str] = None,
) -> List[str]:
    if root_dir is None:
        root_dir = import_path

    status_process_file_list: List[str] = []
    if skip_subfolders:
        status_process_file_list.extend(
            os.path.join(os.path.abspath(root_dir), file)
            for file in os.listdir(root_dir)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and process_status(os.path.join(root_dir, file), process, status)
        )
    else:
        for root, dir, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            status_process_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if process_status(os.path.join(root, file), process, status)
                and file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
            )

    return sorted(status_process_file_list)


def process_status(file_path: str, process: str, status: str) -> bool:
    log_root = uploader.log_rootpath(file_path)
    status_file = os.path.join(log_root, process + "_" + status)
    return os.path.isfile(status_file)


def get_duplicate_file_list(
    import_path: str, skip_subfolders: bool = False, root_dir: Optional[str] = None
) -> List[str]:
    if root_dir is None:
        root_dir = import_path
    duplicate_file_list: List[str] = []
    if skip_subfolders:
        duplicate_file_list.extend(
            os.path.join(os.path.abspath(root_dir), file)
            for file in os.listdir(root_dir)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and is_duplicate(os.path.join(root_dir, file))
        )
    else:
        for root, dir, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            duplicate_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if is_duplicate(os.path.join(root, file))
                and file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
            )

    return sorted(duplicate_file_list)


def is_duplicate(file_path: str) -> bool:
    log_root = uploader.log_rootpath(file_path)
    duplicate_flag_path = os.path.join(log_root, "duplicate")
    return os.path.isfile(duplicate_flag_path)


def preform_process(file_path: str, process: str, rerun: bool = False) -> bool:
    log_root = uploader.log_rootpath(file_path)
    process_succes = os.path.join(log_root, process + "_success")
    upload_succes = os.path.join(log_root, "upload_success")
    preform = not os.path.isfile(upload_succes) and (
        not os.path.isfile(process_succes) or rerun
    )
    return preform


def get_failed_process_file_list(import_path, process):
    failed_process_file_list = []
    for root, dir, files in os.walk(import_path):
        if os.path.join(".mapillary", "logs") in root:
            continue
        failed_process_file_list.extend(
            os.path.join(os.path.abspath(root), file)
            for file in files
            if failed_process(os.path.join(root, file), process)
            and file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
        )

    return sorted(failed_process_file_list)


def failed_process(file_path, process):
    log_root = uploader.log_rootpath(file_path)
    process_failed = os.path.join(log_root, process + "_failed")
    process_failed_true = os.path.isfile(process_failed)
    return process_failed_true


def processed_images_rootpath(filepath: str) -> str:
    return os.path.join(
        os.path.dirname(filepath),
        ".mapillary",
        "processed_images",
        os.path.basename(filepath),
    )


def video_upload(video_file, import_path, verbose=False):
    log_root = uploader.log_rootpath(video_file)
    import_paths = video_import_paths(video_file)
    if not os.path.isdir(import_path):
        os.makedirs(import_path)
    if import_path not in import_paths:
        import_paths.append(import_path)
    else:
        print(
            f"Warning, {video_file} has already been sampled into {import_path}, please make sure all the previously sampled frames are deleted, otherwise the alignment might be incorrect"
        )
    for video_import_path in import_paths:
        if os.path.isdir(video_import_path):
            if len(uploader.get_success_upload_file_list(video_import_path)):
                if verbose:
                    print("no")
                return 1
    return 0


def create_and_log_video_process(video_file, import_path):
    log_root = uploader.log_rootpath(video_file)
    if not os.path.isdir(log_root):
        os.makedirs(log_root)
    # set the log flags for process
    log_process = os.path.join(log_root, "video_process.json")
    import_paths = video_import_paths(video_file)
    if import_path in import_paths:
        return
    import_paths.append(import_path)
    video_process = load_json(log_process)
    video_process.update({"sample_paths": import_paths})
    save_json(video_process, log_process)


def video_import_paths(video_file):
    log_root = uploader.log_rootpath(video_file)
    if not os.path.isdir(log_root):
        return []
    log_process = os.path.join(log_root, "video_process.json")
    if not os.path.isfile(log_process):
        return []
    video_process = load_json(log_process)
    if "sample_paths" in video_process:
        return video_process["sample_paths"]
    return []


def create_and_log_process_in_list(
    process_file_list: List[str],
    process: str,
    status: str,
    verbose: bool = False,
    mapillary_description: Optional[Dict[str, str]] = None,
) -> None:
    if mapillary_description is None:
        mapillary_description = {}
    for image in tqdm(process_file_list, desc="Logging"):
        create_and_log_process(image, process, status, mapillary_description, verbose)


def create_and_log_process(
    image: str,
    process: str,
    status: str,
    mapillary_description: Optional[Any] = None,
    verbose: bool = False,
) -> None:
    if mapillary_description is None:
        mapillary_description = {}

    # set log path
    log_root = uploader.log_rootpath(image)
    # make all the dirs if not there
    if not os.path.isdir(log_root):
        os.makedirs(log_root)

    # set the log flags for process
    log_process = os.path.join(log_root, process)
    log_process_succes = f"{log_process}_success"
    log_process_failed = f"{log_process}_failed"
    log_MAPJson = os.path.join(log_root, process + ".json")

    if not mapillary_description:
        status = "failed"

    if status == "success":
        suffix = str(time.strftime("%Y_%m_%d_%H_%M_%S", time.gmtime()))
        save_json(mapillary_description, log_MAPJson)
        open(log_process_succes, "w").close()
        open(f"{log_process_succes}_{suffix}", "w").close()
        # if there is a failed log from before, remove it
        if os.path.isfile(log_process_failed):
            os.remove(log_process_failed)
    else:
        open(log_process_failed, "w").close()
        suffix = str(time.strftime("%Y_%m_%d_%H_%M_%S", time.gmtime()))
        open(f"{log_process_failed}_{suffix}", "w").close()
        # if there is a success log from before, remove it
        if os.path.isfile(log_process_succes):
            os.remove(log_process_succes)
        # if there is meta data from before, remove it
        if os.path.isfile(log_MAPJson):
            if verbose:
                print(
                    f"Warning, {process} in this run has failed, previously generated properties will be removed."
                )
            os.remove(log_MAPJson)

    decoded_image = force_decode(image)

    ipc.send(
        process,
        {
            "image": decoded_image,
            "status": status,
            "description": mapillary_description,
        },
    )


def user_properties(
    user_name: str,
    import_path: str,
    process_file_list: List[str],
    organization_username: None = None,
    organization_key: None = None,
    private: bool = False,
    verbose: bool = False,
) -> Optional[Dict]:
    # basic
    user_properties = uploader.authenticate_user(user_name)
    if not user_properties:
        print_error("Error, user authentication failed for user " + user_name)
        print(
            "Make sure your user credentials are correct, user authentication is required for images to be uploaded to Mapillary."
        )
        return None
    # organization validation
    if organization_username or organization_key:
        organization_key = process_organization(
            user_properties, organization_username, organization_key, private
        )
        user_properties.update(
            {"MAPOrganizationKey": organization_key, "MAPPrivate": private}
        )

    # remove uneeded credentials
    if "user_upload_token" in user_properties:
        del user_properties["user_upload_token"]

    return user_properties


def user_properties_master(
    user_name,
    import_path,
    process_file_list,
    organization_key=None,
    private=False,
    verbose=False,
):
    try:
        master_key = uploader.get_master_key()
    except:
        print_error("Error, no master key found.")
        print(
            "If you are a user, run the process script without the --master_upload, if you are a Mapillary employee, make sure you have the master key in your config file."
        )
        return None

    user_properties = {
        "MAPVideoSecure": master_key,
        "MAPSettingsUsername": user_name,
    }

    try:
        user_key = api_v3.get_user_key(user_name)
    except:
        print_error(
            f"Error, no user key obtained for the user name {user_name}, check if the user name is spelled correctly and if the master key is correct",
        )
        return None

    if user_key is None:
        return None

    user_properties["MAPSettingsUserKey"] = user_key

    if organization_key:
        user_properties.update({"MAPOrganizationKey": organization_key})
        if private:
            user_properties.update({"MAPPrivate": private})

    return user_properties


def process_organization(
    user_properties, organization_username=None, organization_key=None, private=False
):
    if (
        not "user_upload_token" in user_properties
        or not "MAPSettingsUserKey" in user_properties
    ):
        raise Exception(
            "Error, can not authenticate to validate organization import, upload token or user key missing in the config."
        )
    user_key = user_properties["MAPSettingsUserKey"]
    user_upload_token = user_properties["user_upload_token"]
    if not organization_key and organization_username:
        organization_key = uploader.get_organization_key(
            user_key, organization_username, user_upload_token
        )

    uploader.validate_organization_key(user_key, organization_key, user_upload_token)
    uploader.validate_organization_privacy(
        user_key, organization_key, private, user_upload_token
    )

    return organization_key


def inform_processing_start(
    import_path: str,
    len_process_file_list: int,
    process: str,
    skip_subfolders: bool = False,
) -> None:
    total_file_list = uploader.get_total_file_list(import_path, skip_subfolders)
    print(
        f"Running {process} for {len_process_file_list} images, skipping {len(total_file_list) - len_process_file_list} images."
    )


def load_geotag_points(
    process_file_list: List[str], verbose: bool = False
) -> Tuple[List[str], List[datetime.datetime], List[float], List[float], List[float]]:
    file_list = []
    capture_times = []
    lats = []
    lons = []
    directions = []

    for image in tqdm(process_file_list, desc="Loading geotag points"):
        log_root = uploader.log_rootpath(image)
        geotag_data = get_geotag_data(log_root, image, verbose)
        if not geotag_data:
            create_and_log_process(image, "sequence_process", "failed", verbose=verbose)
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

        # remove previously created duplicate flags
        duplicate_flag_path = os.path.join(log_root, "duplicate")
        if os.path.isfile(duplicate_flag_path):
            os.remove(duplicate_flag_path)

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


def get_images_geotags(process_file_list):
    geotags = []
    missing_geotags = []
    for image in tqdm(sorted(process_file_list), desc="Reading gps data"):
        exif = ExifRead(image)
        timestamp = exif.extract_capture_time()
        lon, lat = exif.extract_lon_lat()
        altitude = exif.extract_altitude()
        if timestamp and lon and lat:
            geotags.append((timestamp, lat, lon, altitude))
            continue
        if timestamp and (not lon or not lat):
            missing_geotags.append((image, timestamp))
        else:
            print_error(f"Error image {image} does not have captured time.")
    return geotags, missing_geotags
