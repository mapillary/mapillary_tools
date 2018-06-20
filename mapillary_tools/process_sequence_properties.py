import os
import uuid
import datetime
import time
import sys
from exif_read import ExifRead
from geo import compute_bearing, gps_distance, diff_bearing
import processing
import uploader

MAX_SEQUENCE_LENGTH = 500


def finalize_sequence_processing(sequence,
                                 final_file_list,
                                 final_directions,
                                 final_capture_times,
                                 import_path,
                                 verbose=False):
    for image, direction, capture_time in zip(final_file_list,
                                              final_directions, final_capture_times):
        mapillary_description = {
            'MAPSequenceUUID': sequence,
            'MAPCompassHeading': {
                "TrueHeading": direction,
                "MagneticHeading": direction
            },
            "MAPCaptureTime": datetime.datetime.strftime(
                capture_time, "%Y_%m_%d_%H_%M_%S_%f")[:-3]
        }
        processing.create_and_log_process(image,
                                          import_path,
                                          "sequence_process",
                                          "success",
                                          mapillary_description,
                                          verbose=verbose)


def process_sequence_properties(import_path,
                                cutoff_distance=600.0,
                                cutoff_time=60.0,
                                interpolate_directions=False,
                                flag_duplicates=False,
                                duplicate_distance=0.1,
                                duplicate_angle=5,
                                offset_angle=0.0,
                                verbose=False,
                                rerun=False,
                                skip_subfolders=False):
    # basic check for all
    import_path = os.path.abspath(import_path)
    if not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " doesnt not exist, exiting...")
        sys.exit()

    sequences = []
    if skip_subfolders:
        process_file_list = processing.get_process_file_list(import_path,
                                                             "sequence_process",
                                                             rerun,
                                                             verbose,
                                                             True,
                                                             import_path)
        if not len(process_file_list):
            if verbose:
                print("No images to run sequence process in root " + import_path)
                print(
                    "If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun")
        else:
            # LOAD TIME AND GPS POINTS ------------------------------------
            file_list, capture_times, lats, lons, directions = processing.load_geotag_points(
                process_file_list, import_path, verbose)
            # ---------------------------------------

            # SPLIT SEQUENCES --------------------------------------
            if len(capture_times) and len(lats) and len(lons):
                sequences.extend(processing.split_sequences(
                    capture_times, lats, lons, file_list, directions, cutoff_time, cutoff_distance, verbose))
        # ---------------------------------------
    else:
        # sequence limited to the root of the files
        for root, dirs, files in os.walk(import_path):
            if ".mapillary" in root:
                continue
            if len(files):
                process_file_list = processing.get_process_file_list(import_path,
                                                                     "sequence_process",
                                                                     rerun,
                                                                     verbose,
                                                                     True,
                                                                     root)
                if not len(process_file_list):
                    if verbose:
                        print("No images to run sequence process in root " + root)
                        print(
                            "If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun")
                    continue

                # LOAD TIME AND GPS POINTS ------------------------------------
                file_list, capture_times, lats, lons, directions = processing.load_geotag_points(
                    process_file_list, import_path, verbose)
                # ---------------------------------------

                # SPLIT SEQUENCES --------------------------------------
                if len(capture_times) and len(lats) and len(lons):
                    sequences.extend(processing.split_sequences(
                        capture_times, lats, lons, file_list, directions, cutoff_time, cutoff_distance, verbose))
                # ---------------------------------------

    # process for each sequence
    for sequence in sequences:
        file_list = sequence["file_list"]
        directions = sequence["directions"]
        latlons = sequence["latlons"]
        capture_times = sequence["capture_times"]

        # COMPUTE DIRECTIONS --------------------------------------
        interpolated_directions = [compute_bearing(ll1[0], ll1[1], ll2[0], ll2[1])
                                   for ll1, ll2 in zip(latlons, latlons[1:])]
        interpolated_directions.append(directions[-1])
        # use interpolated directions if direction not available or if flag for
        # interpolate_directions
        for i, d in enumerate(directions):
            directions[i] = d if (
                d is not None and not interpolate_directions) else (interpolated_directions[i] + offset_angle) % 360.0
        # ---------------------------------------

        # INTERPOLATE TIMESTAMPS, in case of identical timestamps
        capture_times, file_list = processing.interpolate_timestamp(capture_times,
                                                                    file_list)

        final_file_list = file_list[:]
        final_directions = directions[:]
        final_capture_times = capture_times[:]
        # FLAG DUPLICATES --------------------------------------
        if flag_duplicates:
            final_file_list = [file_list[0]]
            final_directions = [directions[0]]
            final_capture_times = [capture_times[0]]
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
                         str(time.strftime("%Y_%m_%d_%H_%M_%S", time.gmtime())), "w").close()
                else:
                    prev_latlon = latlons[k]
                    prev_direction = directions[k]
                    final_file_list.append(filename)
                    final_directions.append(directions[k])
                    final_capture_times.append(capture_times[k])
        # ---------------------------------------

        # FINALIZE ------------------------------------
        for i in range(0, len(final_file_list), MAX_SEQUENCE_LENGTH):
            finalize_sequence_processing(str(uuid.uuid4()),
                                         final_file_list[i:i +
                                                         MAX_SEQUENCE_LENGTH],
                                         final_directions[i:i +
                                                          MAX_SEQUENCE_LENGTH],
                                         final_capture_times[i:i +
                                                             MAX_SEQUENCE_LENGTH],
                                         import_path,
                                         verbose)
