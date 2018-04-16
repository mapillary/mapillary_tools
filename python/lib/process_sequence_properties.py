from lib.exif_read import ExifRead
from lib.geo import compute_bearing, gps_distance, diff_bearing
import lib.processor as processor
import lib.uploader as uploader


def process_sequence_properties(full_image_list, import_path, cutoff_distance, interpolate_directions, remove_duplicates, duplicate_distance, duplicate_angle):
    # load the capture time and lat,lon info, requires that the geotag process
    # has been done
    file_list = []
    capture_times = []
    lats = []
    lons = []
    directions = []

    # LOAD TIME AND GPS POINTS --------------------------------------
    for image in full_image_list:
        mapillary_description = {}
        log_root = uploader.log_rootpath(import_path, image)
        # make all the dirs if not there
        if not os.path.isdir(log_root):
            os.makedirs(log_root)
            print("Warning, geotag process has not been done for image " + image +
                  ", therefore it will not be included in the sequence processing.")
            processor.create_and_log_process(
                image, import_path, mapillary_description, "sequence_process")
            continue
        # check if geotag process was a success
        log_geotag_process_success = os.path.join(
            log_root, "geotag_process_success")
        if not os.path.isfile(log_geotag_process_success):
            print("Warning, geotag process failed for image " + image +
                  ", therefore it will not be included in the sequence processing.")
            processor.create_and_log_process(
                image, import_path, mapillary_description, "sequence_process")
            continue
        # load the geotag json
        geotag_process_json_path = os.path.join(
            log_root, "geotag_process.json")
        try:
            geotag_data = processor.load_json(geotag_process_json_path)
        except:
            print("Warning, geotag data not read for image " + image +
                  ", therefore it will not be included in the sequence processing.")
            processor.create_and_log_process(
                image, import_path, mapillary_description, "sequence_process")
            continue

        # assume all data needed available from this point on
        file_list.append(image)
        capture_times.append(geotag_data["MAPCaptureTime"])
        lats.append(geotag_data["MAPLatitude"])
        lons.append(geotag_data["MAPLongitude"])
        directions.append(geotag_data["MAPCompassHeading"]["TrueHeading"])
    # ---------------------------------------

    # ORDER TIME AND GPS POINTS --------------------------------------
    sort_by_time = zip(capture_times, file_list, lats, lons, directions)
    sort_by_time.sort()
    capture_times, file_list, lats, lons, directions = zip(*sort_by_time)
    latlons = zip(lats, lons)
    # ---------------------------------------

    # COMPUTE DIRECTIONS --------------------------------------
    interpolated_directions = [compute_bearing(ll1[0], ll1[1], ll2[0], ll2[1])
                               for ll1, ll2 in zip(latlons, latlons[1:])]
    interpolated_directions.append(directions[-1])
    # use interpolated directions if direction not available in EXIF or flag
    # for direction compuation
    for i, d in enumerate(directions):
        directions[i] = d if (
            d is not None and not interpolate_directions) else interpolated_directions[i]
    # ---------------------------------------

    # REMOVE DUPLICATES --------------------------------------
    # delete existing duplicate flag
    duplicate_flag_path = os.path.join(log_root, "duplicate")
    if os.path.isfile(duplicate_flag_path):
        os.remove(duplicate_flag_path)
    if remove_duplicates:
        if not duplicate_distance:
            duplicate_distance = 1e-5
        if not duplicate_angle:
            duplicate_angle = 5
        prev_latlon = latlons[0]
        prev_direction = directions[0]
        for i, filename in enumerate(file_list[1:]):
            k = i + 1
            distance = gps_distance(latlons[k], prev_latlon)
            if directions[k] is not None and prev_direction is not None:
                direction_diff = diff_bearing(directions[k], prev_direction)
            else:
                # dont use bearing difference if no bearings are available
                direction_diff = 360
            if distance < duplicate_distance and direction_diff < duplicate_angle:
                open(duplicate_flag_path, "w").close()
            else:
                prev_latlon = latlons[k]
                prev_direction = directions[k]
    # ---------------------------------------

    # SPLIT SEQUENCES --------------------------------------

    # ---------------------------------------
