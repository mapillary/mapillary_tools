import datetime
import uuid
import os
import json
import time
import sys
import shutil
from exif_read import ExifRead
from exif_write import ExifEdit
from exif_aux import verify_exif
from geo import normalize_bearing, interpolate_lat_lon
import config
import uploader
from dateutil.tz import tzlocal
from gps_parser import get_lat_lon_time_from_gpx
from process_video import timestamps_from_filename


STATUS_PAIRS = {"success": "failed",
                "failed": "success"
                }
'''
auxillary processing functions
'''


def exif_time(filename):
    '''
    Get image capture time from exif
    '''
    metadata = ExifRead(filename)
    return metadata.extract_capture_time()


def estimate_sub_second_time(files, interval):
    '''
    Estimate the capture time of a sequence with sub-second precision
    EXIF times are only given up to a second of precission. This function
    uses the given interval between shots to Estimate the time inside that
    second that each picture was taken.
    '''
    if interval <= 0.0:
        return [exif_time(f) for f in files]

    onesecond = datetime.timedelta(seconds=1.0)
    T = datetime.timedelta(seconds=interval)
    for i, f in enumerate(files):
        m = exif_time(f)
        if i == 0:
            smin = m
            smax = m + onesecond
        else:
            m0 = m - T * i
            smin = max(smin, m0)
            smax = min(smax, m0 + onesecond)

    if smin > smax:
        print('Interval not compatible with EXIF times')
        return None
    else:
        s = smin + (smax - smin) / 2
        return [s + T * i for i in range(len(files))]


def geotag_from_exif(process_file_list,
                     import_path,
                     offset_angle,
                     verbose):

    for image in process_file_list:
        geotag_properties = get_geotag_properties_from_exif(
            image, offset_angle)

        create_and_log_process(image,
                               import_path,
                               "geotag_process",
                               "success",
                               geotag_properties,
                               verbose)


def get_geotag_properties_from_exif(image, offset_angle):
    try:
        exif = ExifRead(image)
    except:
        print("Error, EXIF could not be read for image " +
              image + ", geotagging process failed for this image since gps/time properties not read.")
        return None
    # required tags
    try:
        lon, lat = exif.extract_lon_lat()
    except:
        print("Error, " + image +
              " image latitude or longitude tag not in EXIF. Geotagging process failed for this image, since this is required information.")
        return None
    if lat != None and lon != None:
        geotag_properties = {"MAPLatitude": lat}
        geotag_properties["MAPLongitude"] = lon
    else:
        print("Error, " + image + " image latitude or longitude tag not in EXIF. Geotagging process failed for this image, since this is required information.")
        return None
    try:
        timestamp = exif.extract_capture_time()
    except:
        print("Error, " + image +
              " image capture time tag not in EXIF. Geotagging process failed for this image, since this is required information.")
        return None
    geotag_properties["MAPCaptureTime"] = datetime.datetime.strftime(
        timestamp, "%Y_%m_%d_%H_%M_%S_%f")[:-3]

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
        geotag_properties["MAPCompassHeading"] = {"TrueHeading": heading,
                                                  "MagneticHeading": heading}
    except:
        if verbose:
            print("Warning, image direction tag not in EXIF.")

    return geotag_properties


def geotag_from_gpx(process_file_list,
                    import_path,
                    geotag_source_path,
                    offset_time,
                    offset_angle,
                    local_time,
                    interval,
                    timestamp_from_filename,
                    video_duration,
                    sample_interval,
                    video_start_time,
                    use_gps_start_time,
                    duration_ratio,
                    verbose):

    # print time now to warn in case local_time
    if local_time:
        now = datetime.datetime.now(tzlocal())
        if verbose:
            print("Your local timezone is {0}. If not, the geotags will be wrong."
                  .format(now.strftime('%Y-%m-%d %H:%M:%S %Z')))
    else:
        # if not local time to be used, warn UTC will be used
        if verbose:
            print(
                "It is assumed that the image timestamps are in UTC. If not, try using the option --local_time.")

    # read gpx file to get track locations
    gpx = get_lat_lon_time_from_gpx(geotag_source_path,
                                    local_time)

    # Estimate capture time with sub-second precision, reading from image EXIF
    # or estimating from filename
    if timestamp_from_filename:
        if use_gps_start_time or not video_start_time:
            video_start_time = gpx[0][0]

        sub_second_times = timestamps_from_filename(process_file_list,
                                                    video_duration,
                                                    sample_interval,
                                                    video_start_time,
                                                    duration_ratio)
    else:
        sub_second_times = estimate_sub_second_time(process_file_list,
                                                    interval)
    if not sub_second_times:
        print("Error, capture times could not be estimated to sub second precision, images can not be geotagged.")
        create_and_log_process_in_list(process_file_list,
                                       import_path,
                                       "geotag_process"
                                       "failed",
                                       verbose)
        return

    if not gpx:
        print("Error, gpx file was not read, images can not be geotagged.")
        create_and_log_process_in_list(process_file_list,
                                       import_path,
                                       "geotag_process"
                                       "failed",
                                       verbose)
        return

    for image, capture_time in zip(process_file_list,
                                   sub_second_times):

        geotag_properties = get_geotag_properties_from_gpx(
            image, offset_angle, offset_time, capture_time, gpx, verbose)

        create_and_log_process(image,
                               import_path,
                               "geotag_process",
                               "success",
                               geotag_properties,
                               verbose)


def get_geotag_properties_from_gpx(image, offset_angle, offset_time, capture_time, gpx, verbose=False):

    capture_time = capture_time - \
        datetime.timedelta(seconds=offset_time)
    try:
        lat, lon, bearing, elevation = interpolate_lat_lon(gpx,
                                                           capture_time)
    except Exception as e:
        if verbose:
            print(
                "Warning, {}, interpolation of latitude and longitude failed for image {}".format(e, image))
        return None

    corrected_bearing = (bearing + offset_angle) % 360

    if lat != None and lon != None:
        geotag_properties = {"MAPLatitude": lat}
        geotag_properties["MAPLongitude"] = lon
    else:
        if verbose:
            print(
                "Warning, invalid latitude and longitude for image {}".format(image))
        return None

    geotag_properties["MAPCaptureTime"] = datetime.datetime.strftime(capture_time,
                                                                     "%Y_%m_%d_%H_%M_%S_%f")[:-3]
    if elevation:
        geotag_properties["MAPAltitude"] = elevation
    else:
        if verbose:
            print("Warning, image altitude tag not set.")
    if corrected_bearing:
        geotag_properties["MAPCompassHeading"] = {
            "TrueHeading": corrected_bearing, "MagneticHeading": corrected_bearing}
    else:
        if verbose:
            print("Warning, image direction tag not set.")
    return geotag_properties


def geotag_from_csv(process_file_list,
                    import_path,
                    offset_angle,
                    geotag_source_path,
                    verbose):
    pass


def geotag_from_json(process_file_list,
                     import_path,
                     offset_angle,
                     geotag_source_path,
                     verbose):
    pass


def format_orientation(orientation):
    '''
    Convert orientation from clockwise degrees to exif tag

    # see http://sylvana.net/jpegcrop/exif_orientation.html
    '''
    mapping = {
        0: 1,
        90: 8,
        180: 3,
        270: 6,
    }
    if orientation not in mapping:
        raise ValueError("Orientation value has to be 0, 90, 180, or 270")

    return mapping[orientation]


def load_json(file_path):
    try:
        with open(file_path, "rb") as f:
            dict = json.load(f)
        return dict
    except:
        return {}


def save_json(data, file_path):
    with open(file_path, "wb") as f:
        f.write(json.dumps(data, indent=4))


def update_json(data, file_path, process):
    original_data = load_json(file_path)
    original_data[process] = data
    save_json(original_data, file_path)


def get_process_file_list(import_path, process, rerun, verbose):
    process_file_list = []
    for root, dir, files in os.walk(import_path):
        process_file_list.extend(os.path.join(root, file) for file in files if preform_process(
            import_path, root, file, process, rerun) and file.lower().endswith(('jpg', 'jpeg', 'png', 'tif', 'tiff', 'pgm', 'pnm', 'gif')))

    if verbose:
        if process != "sequence_process":
            inform_processing_start(import_path,
                                    len(process_file_list),
                                    process)
        else:
            print("Running sequence_process for {} images".format(
                len(process_file_list)))
    return process_file_list


def preform_process(import_path, root, file, process, rerun):
    file_path = os.path.join(root, file)
    log_root = uploader.log_rootpath(import_path, file_path)
    process_succes = os.path.join(log_root, process + "_success")
    upload_succes = os.path.join(log_root, "upload_success")
    preform = not os.path.isfile(upload_succes) and (
        not os.path.isfile(process_succes) or rerun)
    return preform


def video_upload(video_file, import_path, verbose=False):
    root_path = os.path.dirname(os.path.abspath(video_file))
    log_root = uploader.log_rootpath(root_path, video_file)
    import_paths = video_import_paths(video_file)
    if os.path.isdir(import_path):
        if verbose:
            print("Warning, {} has already been sampled into {}, previously sampled frames will be deleted".format(
                video_file, import_path))
        shutil.rmtree(import_path)
    if not os.path.isdir(import_path):
        os.makedirs(import_path)
    if import_path not in import_paths:
        import_paths.append(import_path)
    for video_import_path in import_paths:
        if os.path.isdir(video_import_path):
            if len(uploader.get_success_upload_file_list(video_import_path)):
                if verbose:
                    print("no")
                return 1
    return 0


def create_and_log_video_process(video_file, import_path):
    root_path = os.path.dirname(os.path.abspath(video_file))
    log_root = uploader.log_rootpath(root_path, video_file)
    if not os.path.isdir(log_root):
        os.makedirs(log_root)
    # set the log flags for process
    log_process = os.path.join(
        log_root, "video_process.json")
    import_paths = video_import_paths(video_file)
    if import_path in import_paths:
        return
    import_paths.append(import_path)
    video_process = load_json(log_process)
    video_process.update({"sample_paths": import_paths})
    save_json(video_process, log_process)


def video_import_paths(video_file):
    root_path = os.path.dirname(os.path.abspath(video_file))
    log_root = uploader.log_rootpath(root_path, video_file)
    if not os.path.isdir(log_root):
        return []
    log_process = os.path.join(
        log_root, "video_process.json")
    if not os.path.isfile(log_process):
        return []
    video_process = load_json(log_process)
    if "sample_paths" in video_process:
        return video_process["sample_paths"]
    return []


def create_and_log_process_in_list(process_file_list,
                                   import_path,
                                   process,
                                   status,
                                   verbose=False,
                                   mapillary_description={}):
    for image in process_file_list:
        create_and_log_process(image,
                               import_path,
                               process,
                               status,
                               mapillary_description,
                               verbose)


def create_and_log_process(image, import_path, process, status, mapillary_description={}, verbose=False):
    # set log path
    log_root = uploader.log_rootpath(import_path, image)
    # make all the dirs if not there
    if not os.path.isdir(log_root):
        os.makedirs(log_root)
    # set the log flags for process
    log_process = os.path.join(
        log_root, process)
    log_process_succes = log_process + "_success"
    log_process_failed = log_process + "_failed"
    log_MAPJson = os.path.join(log_root, process + ".json")

    if status == "success" and not mapillary_description:
        status = "failed"
    elif status == "success":
        try:
            save_json(mapillary_description, log_MAPJson)
            open(log_process_succes, "w").close()
            open(log_process_succes + "_" +
                 str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
            # if there is a failed log from before, remove it
            if os.path.isfile(log_process_failed):
                os.remove(log_process_failed)
        except:
            # if the image description could not have been written to the
            # filesystem, log failed
            print("Error, " + process + " logging failed for image " + image)
            status = "failed"

    if status == "failed":
        open(log_process_failed, "w").close()
        open(log_process_failed + "_" +
             str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
        # if there is a success log from before, remove it
        if os.path.isfile(log_process_succes):
            os.remove(log_process_succes)
        # if there is meta data from before, remove it
        if os.path.isfile(log_MAPJson):
            if verbose:
                print("Warning, {} in this run has failed, previously generated properties will be removed.".format(
                    process))
            os.remove(log_MAPJson)


def user_properties(user_name,
                    import_path,
                    process_file_list,
                    organization_name=None,
                    organization_key=None,
                    private=False,
                    verbose=False):
    # basic
    try:
        user_properties = uploader.authenticate_user(user_name)
    except:
        print("Error, user authentication failed for user " + user_name)
        return None
    # organization validation
    if organization_name or organization_key:
        organization_key = process_organization(user_properties,
                                                organization_name,
                                                organization_key,
                                                private)
        user_properties.update(
            {'MAPOrganizationKey': organization_key, 'MAPPrivate': private})

    # remove uneeded credentials
    if "user_upload_token" in user_properties:
        del user_properties["user_upload_token"]
    if "user_permission_hash" in user_properties:
        del user_properties["user_permission_hash"]
    if "user_signature_hash" in user_properties:
        del user_properties["user_signature_hash"]

    return user_properties


def user_properties_master(user_name,
                           import_path,
                           process_file_list,
                           organization_key=None,
                           private=False,
                           verbose=False):

    try:
        master_key = uploader.get_master_key()
    except:
        print("Error, no master key found.")
        print("If you are a user, run the process script without the --master_upload, if you are a Mapillary employee, make sure you have the master key in your config file.")
        return None

    user_properties = {"MAPVideoSecure": master_key}
    user_properties["MAPSettingsUsername"] = user_name
    try:
        user_key = uploader.get_user_key(user_name)
    except:
        print("Error, no user key obtained for the user name " + user_name +
              ", check if the user name is spelled correctly and if the master key is correct")
        return None
    user_properties['MAPSettingsUserKey'] = user_key

    if organization_key and private:
        user_properties.update(
            {'MAPOrganizationKey': organization_key, 'MAPPrivate': private})

    return user_properties


def process_organization(user_properties, organization_name, organization_key, private):
    if not "user_upload_token" in user_properties or not "MAPSettingsUserKey" in user_properties:
        print(
            "Error, can not authenticate to validate organization import, upload token or user key missing in the config.")
        sys.exit()
    user_key = user_properties["MAPSettingsUserKey"]
    user_upload_token = user_properties["user_upload_token"]
    if not organization_key:
        try:
            organization_key = uploader.get_organization_key(user_key,
                                                             organization_name,
                                                             user_upload_token)
        except:
            print("Error, could not obtain organization key, exiting...")
            sys.exit()

    # validate key
    try:
        uploader.validate_organization_key(user_key,
                                           organization_key,
                                           user_upload_token)
    except:
        print("Error, organization key validation failed, exiting...")
        sys.exit()

    # validate privacy
    try:
        uploader.validate_organization_privacy(user_key,
                                               organization_key,
                                               private,
                                               user_upload_token)
    except:
        print("Error, organization privacy validation failed, exiting...")
        sys.exit()

    return organization_key


def inform_processing_start(import_path, len_process_file_list, process):

    total_file_list = uploader.get_total_file_list(import_path)
    print("Running {} for {} images, skipping {} images.".format(process,
                                                                 len_process_file_list,
                                                                 len(total_file_list) - len_process_file_list))
