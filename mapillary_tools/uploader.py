import copy
import datetime
import json
import os
import socket
import sys

from queue import Queue
import threading
import time
import getpass

from tqdm import tqdm
import requests

from . import processing
from . import config
from . import api_v3
from .exif_read import ExifRead
from . import upload_api_v3
from . import ipc
from .error import print_error
from .utils import force_decode
from .geo import get_timezone_and_utc_offset
from .process_video import get_video_start_time_blackvue
from .uploader_utils import set_video_as_uploaded
from .camera_support.prepare_blackvue_videos import get_blackvue_info
from .gpx_from_blackvue import gpx_from_blackvue, get_points_from_bv

NUMBER_THREADS = int(os.getenv("NUMBER_THREADS", "5"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "50"))
DRY_RUN = bool(os.getenv("DRY_RUN", False))
GLOBAL_CONFIG_FILEPATH = os.getenv(
    "GLOBAL_CONFIG_FILEPATH",
    os.path.join(
        os.path.expanduser("~"), ".config", "mapillary", "configs", api_v3.CLIENT_ID
    ),
)


class UploadThread(threading.Thread):
    q: Queue
    total_task: int

    def __init__(self, queue):
        super().__init__()
        self.q = queue
        self.total_task = self.q.qsize()

    def run(self):
        while not self.q.empty():
            # fetch file from the queue and upload
            try:
                filepath, max_attempts, session = self.q.get(timeout=5)
            except:
                # If it can't get a task after 5 seconds, continue and check if
                # task list is empty
                continue
            progress(
                self.total_task - self.q.qsize(),
                self.total_task,
                f"... {self.q.qsize()} images left.",
            )
            upload_file(filepath, max_attempts, session)
            self.q.task_done()


def flag_finalization(finalize_file_list):
    for file in finalize_file_list:
        finalize_flag = os.path.join(log_rootpath(file), "upload_finalized")
        open(finalize_flag, "a").close()


def get_upload_file_list(import_path, skip_subfolders=False):
    upload_file_list = []
    if skip_subfolders:
        upload_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and preform_upload(import_path, file)
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            upload_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
                and preform_upload(root, file)
            )
    return sorted(upload_file_list)


# get a list of video files in a video_file
# TODO: Create list of supported files instead of adding only these 3
def get_video_file_list(video_file, skip_subfolders=False):
    video_file_list = []
    supported_files = ("mp4", "avi", "tavi", "mov", "mkv")
    if skip_subfolders:
        video_file_list.extend(
            os.path.join(os.path.abspath(video_file), file)
            for file in os.listdir(video_file)
            if (file.lower().endswith(supported_files))
        )
    else:
        for root, _, files in os.walk(video_file):
            video_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if (file.lower().endswith(supported_files))
            )
    return sorted(video_file_list)


def get_total_file_list(import_path, skip_subfolders=False):
    total_file_list = []
    if skip_subfolders:
        total_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            total_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
            )
    return sorted(total_file_list)


def get_failed_upload_file_list(import_path, skip_subfolders=False):
    failed_upload_file_list = []
    if skip_subfolders:
        failed_upload_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and failed_upload(import_path, file)
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            failed_upload_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
                and failed_upload(root, file)
            )

    return sorted(failed_upload_file_list)


def get_success_upload_file_list(import_path, skip_subfolders=False):
    success_upload_file_list = []
    if skip_subfolders:
        success_upload_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and success_upload(import_path, file)
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            success_upload_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
                and success_upload(root, file)
            )

    return sorted(success_upload_file_list)


def success_upload(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    upload_success = os.path.join(log_root, "upload_success")
    upload_finalization = os.path.join(log_root, "upload_finalized")
    manual_upload = os.path.join(log_root, "manual_upload")
    success = (
        os.path.isfile(upload_success) and not os.path.isfile(manual_upload)
    ) or (
        os.path.isfile(upload_success)
        and os.path.isfile(manual_upload)
        and os.path.isfile(upload_finalization)
    )
    return success


def get_success_only_manual_upload_file_list(import_path, skip_subfolders=False):
    success_only_manual_upload_file_list = []
    if skip_subfolders:
        success_only_manual_upload_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and success_only_manual_upload(import_path, file)
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            success_only_manual_upload_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
                and success_only_manual_upload(root, file)
            )

    return sorted(success_only_manual_upload_file_list)


def success_only_manual_upload(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    upload_success = os.path.join(log_root, "upload_success")
    manual_upload = os.path.join(log_root, "manual_upload")
    success = os.path.isfile(upload_success) and os.path.isfile(manual_upload)
    return success


def preform_upload(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    process_success = os.path.join(log_root, "mapillary_image_description_success")
    duplicate = os.path.join(log_root, "duplicate")
    upload_succes = os.path.join(log_root, "upload_success")
    upload = (
        not os.path.isfile(upload_succes)
        and os.path.isfile(process_success)
        and not os.path.isfile(duplicate)
    )
    return upload


def failed_upload(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    process_failed = os.path.join(log_root, "mapillary_image_description_failed")
    duplicate = os.path.join(log_root, "duplicate")
    upload_failed = os.path.join(log_root, "upload_failed")
    failed = (
        os.path.isfile(upload_failed)
        and not os.path.isfile(process_failed)
        and not os.path.isfile(duplicate)
    )
    return failed


def get_finalize_file_list(import_path, skip_subfolders=False):
    finalize_file_list = []
    if skip_subfolders:
        finalize_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and preform_finalize(import_path, file)
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            finalize_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
                and preform_finalize(root, file)
            )

    return sorted(finalize_file_list)


def preform_finalize(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    upload_succes = os.path.join(log_root, "upload_success")
    upload_finalized = os.path.join(log_root, "upload_finalized")
    manual_upload = os.path.join(log_root, "manual_upload")
    finalize = (
        os.path.isfile(upload_succes)
        and not os.path.isfile(upload_finalized)
        and os.path.isfile(manual_upload)
    )
    return finalize


def print_summary(file_list):
    # inform upload has finished and print out the summary
    print(f"Done uploading {len(file_list)} images.")  # improve upload summary


def get_organization_key(user_key, organization_username, upload_token):
    organization_key = None

    organization_usernames = []
    orgs = api_v3.fetch_user_organizations(user_key, upload_token)
    for org in orgs:
        organization_usernames.append(org["name"])
        if org["name"] == organization_username:
            organization_key = org["key"]

    if not organization_key:
        print(
            f"No valid organization key found for organization user name {organization_username}"
        )
        print("Available organization user names for current user are : ")
        print(organization_usernames)
        sys.exit(1)
    return organization_key


def validate_organization_key(user_key, organization_key, upload_token):
    orgs = api_v3.fetch_user_organizations(user_key, upload_token)
    for org in orgs:
        if org["key"] == organization_key:
            return
    raise Exception("Organization key does not exist.")


def validate_organization_privacy(user_key, organization_key, private, upload_token):
    orgs = api_v3.fetch_user_organizations(user_key, upload_token)
    for org in orgs:
        if org["key"] == organization_key:
            if (
                private
                and (("private_repository" not in org) or not org["private_repository"])
            ) or (
                not private
                and (("public_repository" not in org) or not org["public_repository"])
            ):
                print("Organization privacy does not match provided privacy settings.")
                privacy = (
                    "private"
                    if "private_repository" in org and org["private_repository"]
                    else "public"
                )
                privacy_provided = "private" if private else "public"
                print(
                    f"Organization {org['name']} with key {org['key']} is {privacy} while your import privacy settings state {privacy_provided}"
                )
                sys.exit(1)


def progress(count, total, suffix=""):
    """
    Display progress bar
    sources: https://gist.github.com/vladignatyev/06860ec2040cb497f0f3
    """
    bar_len = 60
    filled_len = int(round(bar_len * count / float(total)))
    percents = round(100.0 * count / float(total), 1)
    bar = "=" * filled_len + "-" * (bar_len - filled_len)
    sys.stdout.write(f"[{bar}] {percents}% {suffix}\r")
    sys.stdout.flush()


def prompt_user_for_user_items(user_name):
    print(f"Enter user credentials for user {user_name}:")
    user_email = input("Enter email: ")
    user_password = getpass.getpass("Enter user password: ")
    user_key = api_v3.get_user_key(user_name)
    if not user_key:
        return None
    upload_token = api_v3.get_upload_token(user_email, user_password)
    if not upload_token:
        return None
    return {
        "MAPSettingsUsername": user_name,
        "MAPSettingsUserKey": user_key,
        "user_upload_token": upload_token,
    }


def authenticate_user(user_name):
    if os.path.isfile(GLOBAL_CONFIG_FILEPATH):
        global_config_object = config.load_config(GLOBAL_CONFIG_FILEPATH)
        if user_name in global_config_object.sections():
            user_items = config.load_user(global_config_object, user_name)
            return user_items
    user_items = prompt_user_for_user_items(user_name)
    if not user_items:
        return None
    config.create_config(GLOBAL_CONFIG_FILEPATH)
    config.update_config(GLOBAL_CONFIG_FILEPATH, user_name, user_items)
    return user_items


def authenticate_with_email_and_pwd(user_email, user_password):
    """
    Authenticate the user by passing the email and password.
    This function avoids prompting the command line for user credentials and is useful for calling tools programmatically
    """
    if user_email is None or user_password is None:
        raise ValueError("Could not authenticate user. Missing username or password")
    upload_token = api_v3.get_upload_token(user_email, user_password)
    if not upload_token:
        print(
            "Authentication failed for user email " + user_email + ", please try again."
        )
        sys.exit(1)
    user_key = api_v3.get_user_key(user_email)
    if not user_key:
        print(
            f"User email {user_email} does not exist, please try again or contact Mapillary user support."
        )
        sys.exit(1)

    return {
        "MAPSettingsUsername": user_email,
        "MAPSettingsUserKey": user_key,
        "user_upload_token": upload_token,
    }


def get_master_key():
    master_key = ""
    if os.path.isfile(GLOBAL_CONFIG_FILEPATH):
        global_config_object = config.load_config(GLOBAL_CONFIG_FILEPATH)
        if "MAPAdmin" in global_config_object.sections():
            admin_items = config.load_user(global_config_object, "MAPAdmin")
            if "MAPILLARY_SECRET_HASH" in admin_items:
                master_key = admin_items["MAPILLARY_SECRET_HASH"]
            else:
                create_config = input(
                    "Master upload key does not exist in your global Mapillary config file, set it now?"
                )
                if create_config in ["y", "Y", "yes", "Yes"]:
                    master_key = set_master_key()
        else:
            create_config = input(
                "MAPAdmin section not in your global Mapillary config file, set it now? "
            )
            if create_config in ["y", "Y", "yes", "Yes"]:
                master_key = set_master_key()
    else:
        create_config = input(
            "Master upload key needs to be saved in the global Mapillary config file, which does not exist, create one now? "
        )
        if create_config in ["y", "Y", "yes", "Yes"]:
            config.create_config(GLOBAL_CONFIG_FILEPATH)
            master_key = set_master_key()

    return master_key


def set_master_key():
    config_object = config.load_config(GLOBAL_CONFIG_FILEPATH)
    section = "MAPAdmin"
    if section not in config_object.sections():
        config_object.add_section(section)
    master_key = input("Enter the master key: ")
    if master_key != "":
        config_object = config.set_user_items(
            config_object, section, {"MAPILLARY_SECRET_HASH": master_key}
        )
        config.save_config(config_object, GLOBAL_CONFIG_FILEPATH)
    return master_key


def upload_file(filepath, max_attempts, session):
    """
    Upload file at filepath.
    """
    if max_attempts is None:
        max_attempts = MAX_ATTEMPTS

    exif_read = ExifRead(filepath)

    filename = os.path.basename(filepath)

    try:
        exif_name = exif_read.exif_name()
        _, file_extension = os.path.splitext(filename)
        s3_filename = exif_name + file_extension
    except:
        s3_filename = filename

    try:
        lat, lon, ca, captured_at = exif_read.exif_properties()
        new_session = copy.deepcopy(session)
        session_fields = new_session["fields"]
        session_fields["X-Amz-Meta-Latitude"] = lat
        session_fields["X-Amz-Meta-Longitude"] = lon
        session_fields["X-Amz-Meta-Compass-Angle"] = ca
        session_fields["X-Amz-Meta-Captured-At"] = captured_at
        session = new_session
    except:
        pass

    filepath_keep_original = processing.processed_images_rootpath(filepath)
    filepath_in = filepath
    if os.path.isfile(filepath_keep_original):
        filepath = filepath_keep_original

    if DRY_RUN:
        print("DRY_RUN, Skipping actual image upload. Use this for debug only.")
        return

    displayed_upload_error = False
    for attempt in range(max_attempts):
        try:
            response = upload_api_v3.upload_file(session, filepath, s3_filename)
            if 200 <= response.status_code < 300:
                create_upload_log(filepath_in, "upload_success")
                if displayed_upload_error:
                    print(f"Successful upload of {filename} on attempt {attempt + 1}")
            else:
                create_upload_log(filepath_in, "upload_failed")
                print(response.text)
            break  # attempts
        except requests.RequestException as e:
            print(
                f"HTTP error: {e} on {filename}, will attempt upload again for {max_attempts - attempt - 1} more times"
            )
            displayed_upload_error = True
            time.sleep(5)
        except socket.timeout:
            # Specific timeout handling for Python 2.7
            print(
                f"Timeout error: {filename} (retrying), will attempt upload again for {max_attempts - attempt - 1} more times"
            )
        except OSError as e:
            print(
                f"OS error: {e} on {filename}, will attempt upload again for {max_attempts - attempt - 1} more times"
            )
            time.sleep(5)


def upload_file_list_direct(file_list, number_threads=None, max_attempts=None):
    # set some uploader params first
    if number_threads is None:
        number_threads = NUMBER_THREADS

    if max_attempts is None:
        max_attempts = MAX_ATTEMPTS

    # create upload queue with all files per sequence
    q = Queue()
    for filepath in file_list:
        # FIXME: the third param should be session
        q.put((filepath, max_attempts, None))
    # create uploader threads
    uploaders = [UploadThread(q) for _ in range(number_threads)]

    # start uploaders as daemon threads that can be stopped (ctrl-c)
    try:
        print(f"Uploading with {number_threads} threads")
        for uploader in uploaders:
            uploader.daemon = True
            uploader.start()

        while q.unfinished_tasks:
            time.sleep(1)
        q.join()
    except (KeyboardInterrupt, SystemExit):
        print("\nBREAK: Stopping upload.")
        sys.exit(1)


def upload_file_list_manual(
    file_list,
    sequence_uuid,
    file_params,
    sequence_idx,
    number_threads=None,
    max_attempts=None,
):
    # set some uploader params first
    if number_threads is None:
        number_threads = NUMBER_THREADS
    if max_attempts is None:
        max_attempts = MAX_ATTEMPTS

    first_image = list(file_params.values())[0]

    user_name = first_image["user_name"]
    organization_key = first_image.get("organization_key")
    private = first_image.get("private", False)

    credentials = authenticate_user(user_name)

    upload_options = {
        "token": credentials["user_upload_token"],
    }

    session_path = os.path.join(
        log_folder(file_list[0]), f"session_{sequence_uuid}.json"
    )

    # read session from file
    if os.path.isfile(session_path):
        print(f"Read session from {session_path}")
        with open(session_path, "r") as fp:
            session = json.load(fp)
        # if session not found, delete the file
        resp = upload_api_v3.get_upload_session(session, upload_options)
        if resp.status_code == 404:
            print(f"Invalid session so deleting {session_path}")
            os.remove(session_path)
            session = None
    else:
        session = None

    if not session:
        upload_metadata = {}
        if organization_key:
            upload_metadata["organization_key"] = organization_key
            upload_metadata["private"] = private
        resp = upload_api_v3.create_upload_session(
            "images/sequence", upload_metadata, upload_options
        )
        resp.raise_for_status()
        session = resp.json()
        with open(session_path, "w") as f:
            json.dump(session, f)

    print(f"\nUsing upload session {session['key']}")

    # create upload queue with all files per sequence
    q = Queue()
    for filepath in file_list:
        q.put((filepath, max_attempts, session))

    # create uploader threads
    uploaders = [UploadThread(q) for _ in range(number_threads)]

    # start uploaders as daemon threads that can be stopped (ctrl-c)
    try:
        print(f"Uploading {sequence_idx + 1}. sequence with {number_threads} threads")
        for uploader in uploaders:
            uploader.daemon = True
            uploader.start()

        while q.unfinished_tasks:
            time.sleep(1)
        q.join()
    except (KeyboardInterrupt, SystemExit):
        print("\nBREAK: Stopping upload.")
        sys.exit(1)

    resp = upload_api_v3.close_upload_session(session, None, upload_options)
    resp.raise_for_status()

    print(f"\nClosed upload session {session['key']} so deleting {session_path}")
    os.remove(session_path)

    flag_finalization(file_list)


def log_rootpath(filepath):
    return os.path.join(
        os.path.dirname(filepath),
        ".mapillary",
        "logs",
        os.path.splitext(os.path.basename(filepath))[0],
    )


def log_folder(filepath):
    return os.path.join(os.path.dirname(filepath), ".mapillary", "logs")


def create_upload_log(filepath, status):
    upload_log_root = log_rootpath(filepath)
    upload_log_filepath = os.path.join(upload_log_root, status)
    UPLOAD_STATUS_PAIRS = {
        "upload_success": "upload_failed",
        "upload_failed": "upload_success",
    }
    upload_opposite_log_filepath = os.path.join(
        upload_log_root, UPLOAD_STATUS_PAIRS[status]
    )
    if not os.path.isdir(upload_log_root):
        os.makedirs(upload_log_root)
        open(upload_log_filepath, "w").close()
        open(
            upload_log_filepath
            + "_"
            + str(time.strftime("%Y_%m_%d_%H_%M_%S", time.gmtime())),
            "w",
        ).close()
    else:
        if not os.path.isfile(upload_log_filepath):
            open(upload_log_filepath, "w").close()
            open(
                upload_log_filepath
                + "_"
                + str(time.strftime("%Y_%m_%d_%H_%M_%S", time.gmtime())),
                "w",
            ).close()
        if os.path.isfile(upload_opposite_log_filepath):
            os.remove(upload_opposite_log_filepath)

    decoded_filepath = force_decode(filepath)

    ipc.send(
        "upload",
        {
            "image": decoded_filepath,
            "status": "success" if status == "upload_success" else "failed",
        },
    )


def filter_video_before_upload(video, filter_night_time=False):
    try:
        if not get_blackvue_info(video)["is_Blackvue_video"]:
            print_error(
                "ERROR: Direct video upload is currently only supported for BlackVue DRS900S and BlackVue DR900M cameras. Please use video_process command for other camera files"
            )
            return True
        if get_blackvue_info(video)["camera_direction"] != "Front":
            print_error(
                "ERROR: Currently, only front Blackvue videos are supported on this command. Please use video_process command for backwards camera videos"
            )
            return True
    except:
        print_error("ERROR: Unable to determine video details, skipping video")
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


def send_videos_for_processing(
    video_import_path,
    user_name,
    user_email=None,
    user_password=None,
    skip_subfolders=False,
    organization_key=None,
    private=False,
    master_upload=False,
    sampling_distance=2,
    filter_night_time=False,
    offset_angle=0,
    orientation=0,
):
    # safe checks
    if not os.path.isdir(video_import_path) and not (
        os.path.isfile(video_import_path) and video_import_path.lower().endswith("mp4")
    ):
        print(
            f"video import path {video_import_path} does not exist or is invalid, exiting..."
        )
        sys.exit(1)
    # User Authentication
    if user_email and user_password:
        credentials = authenticate_with_email_and_pwd(user_email, user_password)
    else:
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

        options = {
            "token": credentials["user_upload_token"],
        }

        if not DRY_RUN:
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
