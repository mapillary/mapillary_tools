import os
import uuid
import datetime
import time
from collections import OrderedDict

from exif_read import ExifRead
from geo import compute_bearing, gps_distance, diff_bearing
import processing
import uploader

MAX_SEQUENCE_LENGTH = 500


def finalize_sequence_processing(sequence,
                                 final_file_list,
                                 final_directions,
                                 import_path,
                                 verbose):
    for image, direction in zip(final_file_list,
                                final_directions):
        mapillary_description = {
            'MAPSequenceUUID': sequence,
            'MAPCompassHeading': {
                "TrueHeading": direction,
                "MagneticHeading": direction
            }
        }

        processing.create_and_log_process(image,
                                          import_path,
                                          mapillary_description,
                                          "sequence_process",
                                          verbose)


def interpolate_timestamp(capture_times,
                          file_list):
    '''
    Interpolate time stamps in case of identical timestamps
    '''
    timestamps = []
    num_file = len(file_list)

    time_dict = OrderedDict()

    if num_file < 2:
        return capture_times, file_list

    # trace identical timestamps (always assume capture_times is sorted)
    time_dict = OrderedDict()
    for i, t in enumerate(capture_times):
        if t not in time_dict:
            time_dict[t] = {
                "count": 0,
                "pointer": 0
            }

            interval = 0
            if i != 0:
                interval = (t - capture_times[i - 1]).total_seconds()
                time_dict[capture_times[i - 1]]["interval"] = interval

        time_dict[t]["count"] += 1

    if len(time_dict) >= 2:
        # set time interval as the last available time interval
        time_dict[time_dict.keys()[-1]
                  ]["interval"] = time_dict[time_dict.keys()[-2]]["interval"]
    else:
        # set time interval assuming capture interval is 1 second
        time_dict[time_dict.keys()[0]]["interval"] = time_dict[time_dict.keys()[
            0]]["count"] * 1.

    # interpolate timestampes
    for f, t in zip(file_list,
                    capture_times):
        d = time_dict[t]
        s = datetime.timedelta(
            seconds=d["pointer"] * d["interval"] / float(d["count"]))
        updated_time = t + s
        time_dict[t]["pointer"] += 1
        timestamps.append(updated_time)

    return timestamps, file_list


def process_sequence_properties(import_path,
                                cutoff_distance,
                                cutoff_time,
                                interpolate_directions,
                                remove_duplicates,
                                duplicate_distance,
                                duplicate_angle,
                                verbose,
                                rerun):
    # load the capture time and lat,lon info, requires that the geotag process
    # has been done

    sequences = []
    sequence_index = -1

    # sequence limited to the root of the files
    for root, dirs, files in os.walk(import_path):
        if len(files):
            process_file_list = processing.get_process_file_list(root,
                                                                 "sequence_process",
                                                                 rerun)
            if len(process_file_list):

                file_list = []
                capture_times = []
                lats = []
                lons = []
                directions = []

                # LOAD TIME AND GPS POINTS ------------------------------------
                for image in process_file_list:
                    # check the status of the geotagging
                    log_root = uploader.log_rootpath(import_path,
                                                     image)
                    if not os.path.isdir(log_root):
                        if verbose:
                            print("Warning, geotag process has not been done for image " + image +
                                  ", therefore it will not be included in the sequence processing.")
                        processing.create_and_log_process(image,
                                                          import_path,
                                                          {},
                                                          "sequence_process")
                        continue
                    # check if geotag process was a success
                    log_geotag_process_success = os.path.join(log_root,
                                                              "geotag_process_success")
                    if not os.path.isfile(log_geotag_process_success):
                        if verbose:
                            print("Warning, geotag process failed for image " + image +
                                  ", therefore it will not be included in the sequence processing.")
                        processing.create_and_log_process(image,
                                                          import_path,
                                                          {},
                                                          "sequence_process")
                        continue
                    # load the geotag json
                    geotag_process_json_path = os.path.join(log_root,
                                                            "geotag_process.json")
                    try:
                        geotag_data = processing.load_json(
                            geotag_process_json_path)
                    except:
                        if verbose:
                            print("Warning, geotag data not read for image " + image +
                                  ", therefore it will not be included in the sequence processing.")
                        processing.create_and_log_process(image,
                                                          import_path,
                                                          {},
                                                          "sequence_process")
                        continue

                    # assume all data needed available from this point on
                    file_list.append(image)
                    capture_times.append(datetime.datetime.strptime(geotag_data["MAPCaptureTime"],
                                                                    '%Y_%m_%d_%H_%M_%S_%f'))
                    lats.append(geotag_data["MAPLatitude"])
                    lons.append(geotag_data["MAPLongitude"])
                    directions.append(
                        geotag_data["MAPCompassHeading"]["TrueHeading"])

                    # remove previously created duplicate flags
                    duplicate_flag_path = os.path.join(log_root,
                                                       "duplicate")
                    if os.path.isfile(duplicate_flag_path):
                        os.remove(duplicate_flag_path)

                # ---------------------------------------

                # SPLIT SEQUENCES --------------------------------------
                if len(capture_times) and len(lats) and len(lons):

                    # sort based on time
                    sort_by_time = zip(capture_times,
                                       file_list,
                                       lats,
                                       lons,
                                       directions)
                    sort_by_time.sort()
                    capture_times, file_list, lats, lons, directions = [
                        list(x) for x in zip(*sort_by_time)]
                    latlons = zip(lats,
                                  lons)

                    # interpolate time, in case identical timestamps
                    capture_times, file_list = interpolate_timestamp(capture_times,
                                                                     file_list)

                    # initialize first sequence
                    sequence_index += 1
                    sequences.append({"file_list": [
                        file_list[0]], "directions": [directions[0]], "latlons": [latlons[0]]})

                    if len(file_list) >= 1:
                        # diff in capture time
                        capture_deltas = [
                            t2 - t1 for t1, t2 in zip(capture_times, capture_times[1:])]

                        # distance between consecutive images
                        distances = [gps_distance(ll1, ll2)
                                     for ll1, ll2 in zip(latlons, latlons[1:])]

                        # if cutoff time is given use that, else assume cutoff is
                        # 1.5x median time delta
                        if cutoff_time is None:
                            if verbose:
                                print(
                                    "Warning, sequence cut-off time is None and will therefore be derived based on the median time delta between the consecutive images.")
                            median = sorted(capture_deltas)[
                                len(capture_deltas) // 2]
                            if type(median) is not int:
                                median = median.total_seconds()
                            cutoff_time = 1.5 * median
                        else:
                            cutoff_time = float(cutoff_time)
                        cut = 0
                        for i, filepath in enumerate(file_list[1:]):
                            cut_time = capture_deltas[i].total_seconds(
                            ) > cutoff_time
                            cut_distance = distances[i] > cutoff_distance
                            if cut_time or cut_distance:
                                cut += 1
                                # delta too big, start new sequence
                                sequence_index += 1
                                sequences.append({"file_list": [
                                    filepath], "directions": [directions[1:][i]], "latlons": [latlons[1:][i]]})
                                if verbose:
                                    if cut_distance:
                                        print('Cut {}: Delta in distance {} meters is bigger than cutoff_distance {} meters at {}'.format(
                                            cut, distances[i], cutoff_distance, file_list[i + 1]))
                                    elif cut_time:
                                        print('Cut {}: Delta in time {} seconds is bigger then cutoff_time {} seconds at {}'.format(
                                            cut, capture_deltas[i].total_seconds(), cutoff_time, file_list[i + 1]))
                            else:
                                # delta not too big, continue with current
                                # group
                                sequences[sequence_index]["file_list"].append(
                                    filepath)
                                sequences[sequence_index]["directions"].append(
                                    directions[1:][i])
                                sequences[sequence_index]["latlons"].append(
                                    latlons[1:][i])
                # ---------------------------------------

    # process for each sequence
    for sequence in sequences:
        file_list = sequence["file_list"]
        directions = sequence["directions"]
        latlons = sequence["latlons"]

        # COMPUTE DIRECTIONS --------------------------------------
        interpolated_directions = [compute_bearing(ll1[0], ll1[1], ll2[0], ll2[1])
                                   for ll1, ll2 in zip(latlons, latlons[1:])]
        interpolated_directions.append(directions[-1])
        # use interpolated directions if direction not available or if flag for
        # interpolate_directions
        for i, d in enumerate(directions):
            directions[i] = d if (
                d is not None and not interpolate_directions) else interpolated_directions[i]
        # ---------------------------------------

        final_file_list = file_list[:]
        final_directions = directions[:]

        # FLAG DUPLICATES --------------------------------------
        if remove_duplicates:
            final_file_list = [file_list[0]]
            final_directions = [directions[0]]
            prev_latlon = latlons[0]
            prev_direction = directions[0]
            for i, filename in enumerate(file_list[1:]):
                log_root = uploader.log_rootpath(import_path,
                                                 filename)
                duplicate_flag_path = os.path.join(log_root,
                                                   "duplicate")
                sequence_process_success_path = os.path.join(log_root,
                                                             "sequence_process_success")
                k = i + 1
                distance = gps_distance(latlons[k],
                                        prev_latlon)
                if directions[k] is not None and prev_direction is not None:
                    direction_diff = diff_bearing(directions[k],
                                                  prev_direction)
                else:
                    # dont use bearing difference if no bearings are
                    # available
                    direction_diff = 360
                if distance < duplicate_distance and direction_diff < duplicate_angle:
                    open(duplicate_flag_path, "w").close()
                    open(sequence_process_success_path, "w").close()
                    open(sequence_process_success_path + "_" +
                         str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
                else:
                    prev_latlon = latlons[k]
                    prev_direction = directions[k]
                    final_file_list.append(filename)
                    final_directions.append(directions[k])
        # ---------------------------------------

        # FINALIZE ------------------------------------
        for i in range(0, len(final_file_list), MAX_SEQUENCE_LENGTH):
            finalize_sequence_processing(str(uuid.uuid4()),
                                         final_file_list[i:i +
                                                         MAX_SEQUENCE_LENGTH],
                                         final_directions[i:i +
                                                          MAX_SEQUENCE_LENGTH],
                                         import_path,
                                         verbose)
