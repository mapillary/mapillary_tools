import datetime
import os
import subprocess
import typing as T

from . import processing
from . import uploader
from .exif_write import ExifEdit
from .ffprobe import FFProbe

ZERO_PADDING = 6
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT_2 = "%Y-%m-%dT%H:%M:%S.000000Z"


def timestamp_from_filename(
    video_filename: str,
    filename: str,
    start_time: datetime.datetime,
    interval=2.0,
    adjustment=1.0,
) -> datetime.datetime:
    seconds = (
        (int(filename.rstrip(".jpg").replace(f"{video_filename}_", "").lstrip("0")) - 1)
        * interval
        * adjustment
    )

    return start_time + datetime.timedelta(seconds=seconds)


def timestamps_from_filename(
    video_filename: str,
    full_image_list: T.List[str],
    start_time: datetime.datetime,
    interval=2.0,
    adjustment=1.0,
) -> T.List[datetime.datetime]:
    capture_times: T.List[datetime.datetime] = []
    for image in full_image_list:
        capture_times.append(
            timestamp_from_filename(
                video_filename,
                os.path.basename(image),
                start_time,
                interval,
                adjustment,
            )
        )
    return capture_times


def sample_video(
    video_import_path: str,
    import_path: str,
    video_sample_interval=2.0,
    video_start_time=None,
    video_duration_ratio=1.0,
    skip_subfolders=False,
):
    if not os.path.exists(video_import_path):
        raise RuntimeError(f'Error, video path "{video_import_path}" does not exist')

    video_list = (
        uploader.get_video_file_list(video_import_path, skip_subfolders)
        if os.path.isdir(video_import_path)
        else [video_import_path]
    )

    if os.path.isdir(import_path) or os.path.isfile(import_path):
        raise RuntimeError(
            f'The import path "{import_path}" for storing extracted frames already exists. Either delete the current import_path or choose another import_path.'
        )

    for video in video_list:
        per_video_import_path = processing.video_sample_path(import_path, video)
        if not os.path.isdir(per_video_import_path):
            os.makedirs(per_video_import_path)

        extract_frames(
            video,
            per_video_import_path,
            video_sample_interval,
            video_start_time,
            video_duration_ratio,
        )


def extract_frames(
    video_file: str,
    import_path: str,
    video_sample_interval: float = 2.0,
    video_start_time: float = None,
    video_duration_ratio: float = 1.0,
) -> None:
    video_filename, ext = os.path.splitext(os.path.basename(video_file))
    command = [
        "ffmpeg",
        "-i",
        video_file,
        "-loglevel",
        "quiet",
        "-vf",
        f"fps=1/{video_sample_interval}",
        "-qscale",
        "1",
        "-nostdin",
        f"{os.path.join(import_path, video_filename)}_%0{ZERO_PADDING}d.jpg",
    ]

    print(f"Extracting frames: {' '.join(command)}")
    try:
        subprocess.call(command)
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg not found. Please make sure it is installed in your PATH. See https://github.com/mapillary/mapillary_tools#video-support for instructions"
        )

    if video_start_time is not None:
        video_start_time_obj = datetime.datetime.utcfromtimestamp(
            video_start_time / 1000.0
        )
    else:
        video_start_time_obj = get_video_start_time(video_file)

    insert_video_frame_timestamp(
        video_filename,
        import_path,
        video_start_time_obj,
        video_sample_interval,
        video_duration_ratio,
    )


def insert_video_frame_timestamp(
    video_filename: str,
    video_sampling_path: str,
    start_time: datetime.datetime,
    sample_interval: float = 2.0,
    duration_ratio: float = 1.0,
) -> None:
    # get list of file to process
    frame_list = uploader.get_total_file_list(video_sampling_path)

    if not frame_list:
        # WARNING LOG
        print("No video frames were sampled.")
        return

    video_frame_timestamps = timestamps_from_filename(
        video_filename, frame_list, start_time, sample_interval, duration_ratio
    )

    for image, timestamp in zip(frame_list, video_frame_timestamps):
        exif_edit = ExifEdit(image)
        exif_edit.add_date_time_original(timestamp)
        exif_edit.write()


def get_video_duration_and_end_time(
    video_file: str,
) -> T.Tuple[float, datetime.datetime]:
    probe = FFProbe(video_file)

    duration_str = probe.video[0]["duration"]
    try:
        duration = float(duration_str)
    except (TypeError, ValueError) as e:
        raise RuntimeError(
            f"could not parse duration {duration_str} from video {video_file} due to {e}"
        )

    time_string = probe.video[0]["tags"]["creation_time"]
    try:
        creation_time = datetime.datetime.strptime(time_string, TIME_FORMAT)
    except ValueError:
        try:
            creation_time = datetime.datetime.strptime(time_string, TIME_FORMAT_2)
        except ValueError:
            raise RuntimeError(
                f"Failed to parse {time_string} as {TIME_FORMAT} or {TIME_FORMAT_2}"
            )

    return duration, creation_time


def get_video_start_time(video_file: str) -> datetime.datetime:
    duration, video_end_time = get_video_duration_and_end_time(video_file)
    return video_end_time - datetime.timedelta(seconds=duration)
