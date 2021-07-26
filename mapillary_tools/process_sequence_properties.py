import typing as T
import datetime
import os
import uuid

from . import image_log
from . import processing, types
from .geo import compute_bearing, gps_distance, diff_bearing, gps_speed

MAX_SEQUENCE_LENGTH = 500
MAX_CAPTURE_SPEED = 45  # in m/s


def load_geotag_points(
    process_file_list: T.List[str],
) -> T.Tuple[
    T.List[str], T.List[datetime.datetime], T.List[float], T.List[float], T.List[float]
]:
    file_list = []
    capture_times = []
    lats = []
    lons = []
    directions = []

    for image in process_file_list:
        ret = image_log.read_process_data_from_memory(image, "geotag_process")
        if ret is None:
            continue
        status, geotag_data = ret
        if status != "success":
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

        image_log.unmark_duplicated(image)

    return file_list, capture_times, lats, lons, directions


def split_sequences(
    capture_times: T.List[datetime.datetime],
    lats: T.List[float],
    lons: T.List[float],
    file_list: T.List[str],
    directions: T.List[float],
    cutoff_time: float,
    cutoff_distance: float,
) -> T.List[T.Dict]:
    sequences: T.List[T.Dict] = []
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
            else:
                # delta not too big, continue with current
                # group
                sequences[sequence_index]["file_list"].append(filepath)
                sequences[sequence_index]["directions"].append(directions[1:][i])
                sequences[sequence_index]["latlons"].append(latlons[1:][i])
                sequences[sequence_index]["capture_times"].append(capture_times[1:][i])

    return sequences


def finalize_sequence_processing(
    sequence,
    final_file_list,
    final_directions,
    final_capture_times,
):
    for image, direction, capture_time in zip(
        final_file_list, final_directions, final_capture_times
    ):
        mapillary_description: types.Sequence = {
            "MAPSequenceUUID": sequence,
            "MAPCompassHeading": {
                "TrueHeading": direction,
                "MagneticHeading": direction,
            },
            "MAPCaptureTime": datetime.datetime.strftime(
                capture_time, "%Y_%m_%d_%H_%M_%S_%f"
            )[:-3],
        }
        image_log.create_and_log_process_in_memory(
            image, "sequence_process", "success", mapillary_description
        )


def process_sequence_properties(
    import_path,
    cutoff_distance=600.0,
    cutoff_time=60.0,
    interpolate_directions=False,
    keep_duplicates=False,
    duplicate_distance=0.1,
    duplicate_angle=5,
    offset_angle=0.0,
    rerun=False,
    skip_subfolders=False,
):
    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        raise RuntimeError(f"Error, import directory {import_path} does not exist")

    sequences = find_sequences(
        cutoff_distance, cutoff_time, import_path, rerun, skip_subfolders
    )

    # process for each sequence
    for sequence in sequences:
        file_list = sequence["file_list"]
        directions = sequence["directions"]
        latlons = sequence["latlons"]
        capture_times = sequence["capture_times"]

        # COMPUTE DIRECTIONS --------------------------------------
        interpolated_directions = [
            compute_bearing(ll1[0], ll1[1], ll2[0], ll2[1])
            for ll1, ll2 in zip(latlons[:-1], latlons[1:])
        ]
        if len(interpolated_directions):
            interpolated_directions.append(interpolated_directions[-1])
        else:
            interpolated_directions.append(directions[-1])
        # use interpolated directions if direction not available or if flag for
        # interpolate_directions
        for i, d in enumerate(directions):
            directions[i] = (
                d
                if (d is not None and not interpolate_directions)
                else (interpolated_directions[i] + offset_angle) % 360.0
            )
        # ---------------------------------------

        # COMPUTE SPEED -------------------------------------------
        computed_delta_ts = [
            (t1 - t0).total_seconds()
            for t0, t1 in zip(capture_times[:-1], capture_times[1:])
        ]
        computed_distances = [
            gps_distance(l1, l0) for l0, l1 in zip(latlons[:-1], latlons[1:])
        ]
        computed_speed = gps_speed(
            computed_distances, computed_delta_ts
        )  # in meters/second
        if len([x for x in computed_speed if x > MAX_CAPTURE_SPEED]) > 0:
            print(
                f"Warning: The distance in sequence including images\n{file_list[0]}\nto\n{file_list[-1]}\nis too large for the time difference (very high apparent capture speed). Are you sure timestamps and locations are correct?"
            )

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
                k = i + 1
                distance = gps_distance(latlons[k], prev_latlon)
                if directions[k] is not None and prev_direction is not None:
                    direction_diff = diff_bearing(directions[k], prev_direction)
                else:
                    # dont use bearing difference if no bearings are
                    # available
                    direction_diff = 360

                if distance < duplicate_distance and direction_diff < duplicate_angle:
                    image_log.mark_as_duplicated(filename)
                    # FIXME: understand why
                    # log_root = uploader.log_rootpath(filename)
                    # sequence_process_success_path = os.path.join(
                    #     log_root, "sequence_process_success"
                    # )
                    # open(sequence_process_success_path, "w").close()
                    # open(
                    #     sequence_process_success_path
                    #     + "_"
                    #     + str(time.strftime("%Y_%m_%d_%H_%M_%S", time.gmtime())),
                    #     "w",
                    # ).close()
                else:
                    prev_latlon = latlons[k]
                    prev_direction = directions[k]
                    final_file_list.append(filename)
                    final_directions.append(directions[k])
                    final_capture_times.append(capture_times[k])
        # ---------------------------------------

        # FINALIZE ------------------------------------
        for i in range(0, len(final_file_list), MAX_SEQUENCE_LENGTH):
            finalize_sequence_processing(
                str(uuid.uuid4()),
                final_file_list[i : i + MAX_SEQUENCE_LENGTH],
                final_directions[i : i + MAX_SEQUENCE_LENGTH],
                final_capture_times[i : i + MAX_SEQUENCE_LENGTH],
            )


def find_sequences(
    cutoff_distance, cutoff_time, import_path, rerun, skip_subfolders
) -> T.List[T.Dict]:
    def _split(process_file_list: T.List[str]) -> T.List[T.Dict]:
        if not process_file_list:
            return []

        (
            file_list,
            capture_times,
            lats,
            lons,
            directions,
        ) = load_geotag_points(process_file_list)

        if capture_times and lats and lons:
            return split_sequences(
                capture_times,
                lats,
                lons,
                file_list,
                directions,
                cutoff_time,
                cutoff_distance,
            )
        else:
            return []

    if skip_subfolders:
        process_file_list = image_log.get_process_file_list(
            import_path,
            "mapillary_image_description",
            rerun=rerun,
            skip_subfolders=True,
        )
        return _split(process_file_list)
    else:
        sequences = []

        # sequence limited to the root of the files
        for root, dirs, files in os.walk(import_path, topdown=True):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            process_file_list = image_log.get_process_file_list(
                root,
                "mapillary_image_description",
                rerun=rerun,
                skip_subfolders=True,
            )
            sequences.extend(_split(process_file_list))

        return sequences
