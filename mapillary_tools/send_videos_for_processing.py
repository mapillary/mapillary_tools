import datetime
import os
import sys

from tqdm import tqdm

from . import ipc, upload_api_v3
from .camera_support.prepare_blackvue_videos import get_blackvue_info
from .error import print_error
from .geo import get_timezone_and_utc_offset
from .gpx_from_blackvue import get_points_from_bv, gpx_from_blackvue
from .process_video import get_video_start_time_blackvue
from .uploader import (
    get_video_file_list,
    DRY_RUN,
    create_upload_log,
)
from .login import authenticate_user


def send_videos_for_processing(
    import_path,
    video_import_path,
    user_name,
    skip_subfolders=False,
    organization_key=None,
    private=False,
    master_upload=False,
    sampling_distance=2,
    filter_night_time=False,
    offset_angle=0,
    orientation=0,
    verbose=False,
):
    # safe checks
    if not os.path.isdir(video_import_path) and not (
        os.path.isfile(video_import_path) and video_import_path.lower().endswith("mp4")
    ):
        print(
            f"video import path {video_import_path} does not exist or is invalid, exiting..."
        )
        sys.exit(1)
    credentials = authenticate_user(user_name)
    if credentials is None:
        print(f"Error, user authentication failed for user {user_name}")
        sys.exit(1)

    # upload all videos in the import path
    # get a list of all videos first
    all_videos = (
        get_video_file_list(video_import_path, skip_subfolders)
        if os.path.isdir(video_import_path)
        else [video_import_path]
    )
    total_videos_count = len(all_videos)

    all_videos = [
        x for x in all_videos if os.path.basename(os.path.dirname(x)) != "uploaded"
    ]  # Filter already uploaded videos
    uploaded_videos_count = total_videos_count - len(all_videos)

    all_videos = [
        x for x in all_videos if os.path.basename(os.path.dirname(x)) != "stationary"
    ]
    all_videos = [
        x for x in all_videos if os.path.basename(os.path.dirname(x)) != "no_gps_data"
    ]
    all_videos = [
        x for x in all_videos if os.path.basename(os.path.dirname(x)) != "nighttime"
    ]
    skipped_videos_count = total_videos_count - uploaded_videos_count - len(all_videos)

    progress = {
        "total": total_videos_count,
        "uploaded": uploaded_videos_count,
        "skipped": skipped_videos_count,
    }

    ipc.send("progress", progress)

    for video in tqdm(all_videos, desc="Uploading videos for processing"):
        print(f"Preparing video {os.path.basename(video)} for upload")

        if filter_video_before_upload(video, filter_night_time):
            progress["skipped"] += 1
            continue

        video_start_time = get_video_start_time_blackvue(video)
        # Correct timestamp in case camera time zone is not set correctly. If timestamp is not UTC, sync with GPS track will fail.
        # Only hours are corrected, so that second offsets are taken into
        # account correctly
        gpx_points = get_points_from_bv(video)
        gps_video_start_time = gpx_points[0][0]
        delta_t = video_start_time - gps_video_start_time
        if delta_t.days > 0:
            hours_diff_to_utc = round(delta_t.total_seconds() / 3600)
        else:
            hours_diff_to_utc = round(delta_t.total_seconds() / 3600) * -1
        video_start_time_utc = video_start_time + datetime.timedelta(
            hours=hours_diff_to_utc
        )
        video_start_timestamp = int(
            ((video_start_time_utc - datetime.datetime(1970, 1, 1)).total_seconds())
            * 1000
        )

        metadata = {
            "camera_angle_offset": float(offset_angle),
            "exif_frame_orientation": orientation,
            "images_upload_v2": True,
            "make": "Blackvue",
            "model": "DR900S-1CH",
            "private": private,
            "sample_interval_distance": float(sampling_distance),
            "sequence_key": "test_sequence",  # TODO: What is the sequence key?
            "video_start_time": video_start_timestamp,
        }

        if organization_key is not None:
            metadata["organization_key"] = organization_key

        if master_upload is not None:
            metadata["user_key"] = master_upload

        if not DRY_RUN:
            options = {
                "token": credentials["user_upload_token"],
            }
            upload_video(video, metadata, options)

        progress["uploaded"] += 1

    ipc.send("progress", progress)

    print("Upload completed")


def upload_video(video, metadata, options, max_retries=20):
    resp = upload_api_v3.create_upload_session("videos/blackvue", metadata, options)
    resp.raise_for_status()
    session = resp.json()

    file_key = "uploaded"

    for attempt in range(max_retries):
        print("Uploading...")
        response = upload_api_v3.upload_file(session, video, file_key)
        if 200 <= response.status_code <= 300:
            break
        else:
            print(f"Upload status {response.status_code}")
            print(f"Upload request.url {response.request.url}")
            print(f"Upload response.text {response.text}")
            print(f"Upload request.headers {response.request.headers}")
            if attempt >= max_retries - 1:
                print(f"Max attempts reached. Failed to upload video {video}")
                return

    resp = upload_api_v3.close_upload_session(session, None, options)
    resp.raise_for_status()

    set_video_as_uploaded(video)
    create_upload_log(video, "upload_success")
    print(f"Uploaded {file_key} successfully")


def filter_video_before_upload(video, filter_night_time=False):
    blackvue_info = get_blackvue_info(video)

    if not blackvue_info["is_Blackvue_video"]:
        print_error(
            "ERROR: Direct video upload is currently only supported for BlackVue DRS900S and BlackVue DR900M cameras. Please use video_process command for other camera files"
        )
        return True
    if blackvue_info.get("camera_direction") != "Front":
        print_error(
            "ERROR: Currently, only front Blackvue videos are supported on this command. Please use video_process command for backwards camera videos"
        )
        return True

    [gpx_file_path, isStationaryVid] = gpx_from_blackvue(
        video, use_nmea_stream_timestamp=False
    )
    video_start_time = get_video_start_time_blackvue(video)
    if isStationaryVid:
        if not gpx_file_path:
            if os.path.basename(os.path.dirname(video)) != "no_gps_data":
                no_gps_folder = os.path.dirname(video) + "/no_gps_data/"
                if not os.path.exists(no_gps_folder):
                    os.mkdir(no_gps_folder)
                os.rename(video, no_gps_folder + os.path.basename(video))
            print_error(f"Skipping file {video} due to file not containing gps data")
            return True
        if os.path.basename(os.path.dirname(video)) != "stationary":
            stationary_folder = os.path.dirname(video) + "/stationary/"
            if not os.path.exists(stationary_folder):
                os.mkdir(stationary_folder)
            os.rename(video, stationary_folder + os.path.basename(video))
            os.rename(
                gpx_file_path, stationary_folder + os.path.basename(gpx_file_path)
            )
        print_error(f"Skipping file {video} due to camera being stationary")
        return True

    if not isStationaryVid:
        gpx_points = get_points_from_bv(video)
        if filter_night_time:
            # Unsupported feature: Check if video was taken at night
            # TODO: Calculate sun incidence angle and decide based on threshold
            # angle
            sunrise_time = 9
            sunset_time = 18
            try:
                timeZoneName, local_timezone_offset = get_timezone_and_utc_offset(
                    gpx_points[0][1], gpx_points[0][2]
                )
                if timeZoneName is None:
                    print("Could not determine local time. Video will be uploaded")
                    return False
                local_video_datetime = video_start_time + local_timezone_offset
                if local_video_datetime.time() < datetime.time(
                    sunrise_time, 0, 0
                ) or local_video_datetime.time() > datetime.time(sunset_time, 0, 0):
                    if os.path.basename(os.path.dirname(video)) != "nighttime":
                        night_time_folder = os.path.dirname(video) + "/nighttime/"
                    if not os.path.exists(night_time_folder):
                        os.mkdir(night_time_folder)
                    os.rename(video, night_time_folder + os.path.basename(video))
                    os.rename(
                        gpx_file_path,
                        night_time_folder + os.path.basename(gpx_file_path),
                    )
                    print_error(
                        f"Skipping file {video} due to video being recorded at night (Before 9am or after 6pm)"
                    )
                    return True
            except Exception as e:
                print(
                    f"Unable to determine time of day. Exception raised: {e} \n Video will be uploaded"
                )
        return False


def set_video_as_uploaded(video):
    current_base_path = os.path.dirname(video)
    new_base_path = os.path.join(current_base_path, "uploaded")

    if not os.path.exists(new_base_path):
        os.mkdir(new_base_path)

    # Move video to uploaded folder
    new_video_path = os.path.join(new_base_path, os.path.basename(video))
    os.rename(video, new_video_path)

    # Move GPX file
    basename = os.path.basename(video)
    video_key = os.path.splitext(basename)[0]
    gpx_filename = f"{video_key}.gpx"
    gpx_path = os.path.join(current_base_path, gpx_filename)
    new_gpx_path = os.path.join(new_base_path, gpx_filename)
    os.rename(gpx_path, new_gpx_path)
