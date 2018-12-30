import os
import uuid
import datetime
import time
import sys
from exif_read import ExifRead
from geo import compute_bearing, gps_distance, diff_bearing, gps_speed
import processing
import uploader
from tqdm import tqdm
from .error import print_error

MAX_SEQUENCE_LENGTH = 500
MAX_CAPTURE_SPEED = 45  # in m/s


def finalize_sequence_processing(sequence,
                                 final_file_list,
                                 final_directions,
                                 final_capture_times,
                                 import_path,
                                 verbose=False):
    for image, direction, capture_time in tqdm(zip(final_file_list,
                                                   final_directions, final_capture_times), desc="Finalizing sequence process"):
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
                                          "sequence_process",
                                          "success",
                                          mapillary_description,
                                          verbose=verbose)


def process_sequence_properties(import_path,
                                cutoff_distance=600.0,
                                cutoff_time=60.0,
                                interpolate_directions=False,
                                keep_duplicates=False,
                                duplicate_distance=0.1,
                                duplicate_angle=5,
                                offset_angle=0.0,
                                verbose=False,
                                rerun=False,
                                skip_subfolders=False,
                                video_import_path=None):

    # sanity check if video file is passed
    if video_import_path and not os.path.isdir(video_import_path) and not os.path.isfile(video_import_path):
        print("Error, video path " + video_import_path +
              " does not exist, exiting...")
        sys.exit(1)

    # in case of video processing, adjust the import path
    if video_import_path:
        # set sampling path
        video_sampling_path = "mapillary_sampled_video_frames"
        video_dirname = video_import_path if os.path.isdir(
            video_import_path) else os.path.dirname(video_import_path)
        import_path = os.path.join(os.path.abspath(import_path), video_sampling_path) if import_path else os.path.join(
            os.path.abspath(video_dirname), video_sampling_path)

    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        print_error("Error, import directory " + import_path +
                    " does not exist, exiting...")
        sys.exit(1)

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
                process_file_list, verbose)
            # ---------------------------------------

            # SPLIT SEQUENCES --------------------------------------
            if len(capture_times) and len(lats) and len(lons):
                sequences.extend(processing.split_sequences(
                    capture_times, lats, lons, file_list, directions, cutoff_time, cutoff_distance, verbose))
        # ---------------------------------------
    else:
        # sequence limited to the root of the files
        for root, dirs, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
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
                    process_file_list, verbose)
                # ---------------------------------------
                # SPLIT SEQUENCES --------------------------------------
                if len(capture_times) and len(lats) and len(lons):
                    sequences.extend(processing.split_sequences(
                        capture_times, lats, lons, file_list, directions, cutoff_time, cutoff_distance, verbose))
                # ---------------------------------------
    if not keep_duplicates:
        if verbose:
            print("Flagging images as duplicates if consecutive distance difference less than {} and angle difference less than {}".format(
                duplicate_distance, duplicate_angle))

    # process for each sequence
    for sequence in sequences:
        file_list = sequence["file_list"]
        directions = sequence["directions"]
        latlons = sequence["latlons"]
        capture_times = sequence["capture_times"]

        # COMPUTE DIRECTIONS --------------------------------------
        interpolated_directions = [compute_bearing(ll1[0], ll1[1], ll2[0], ll2[1])
                                   for ll1, ll2 in zip(latlons[:-1], latlons[1:])]
        if len(interpolated_directions):
            interpolated_directions.append(interpolated_directions[-1])
        else:
            interpolated_directions.append(directions[-1])
        # use interpolated directions if direction not available or if flag for
        # interpolate_directions
        for i, d in enumerate(directions):
            directions[i] = d if (
                d is not None and not interpolate_directions) else (interpolated_directions[i] + offset_angle) % 360.0
        # ---------------------------------------

        # COMPUTE SPEED -------------------------------------------
        computed_delta_ts = [(t1 - t0).total_seconds()
                             for t0, t1 in zip(capture_times[:-1], capture_times[1:])]
        computed_distances = [gps_distance(l1, l0)
                              for l0, l1 in zip(latlons[:-1], latlons[1:])]
        computed_speed = gps_speed(
            computed_distances, computed_delta_ts)  # in meters/second
        if len([x for x in computed_speed if x > MAX_CAPTURE_SPEED]) > 0:
            print("Warning: The distance in sequence including images\n{}\nto\n{}\nis too large for the time difference (very high apparent capture speed). Are you sure timestamps and locations are correct?".format(
                file_list[0], file_list[-1]))

        # INTERPOLATE TIMESTAMPS, in case of identical timestamps
        capture_times = processing.interpolate_timestamp(capture_times)

        final_file_list = file_list[:]
        final_directions = directions[:]
        final_capture_times = capture_times[:]
        # FLAG DUPLICATES --------------------------------------
        if not keep_duplicates:
            final_file_list = [file_list[0]]
            final_directions = [directions[0]]
            final_capture_times = [capture_times[0]]
            prev_latlon = latlons[0]
            prev_direction = directions[0]
            for i, filename in enumerate(file_list[1:]):
                log_root = uploader.log_rootpath(filename)
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
                    # don't use bearing difference if no bearings are
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
    print("Sub process ended")
