import datetime
import os
import shutil
import subprocess
import typing as T
import logging

from . import image_log, ffprobe
from .exif_write import ExifEdit

ZERO_PADDING = 6
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT_2 = "%Y-%m-%dT%H:%M:%S.000000Z"
LOG = logging.getLogger(__name__)


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


def video_sample_path(import_path: str, video_file_path: str) -> str:
    video_filename = os.path.basename(video_file_path)
    return os.path.join(import_path, video_filename)


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
        image_log.get_video_file_list(video_import_path, skip_subfolders, abs_path=True)
        if os.path.isdir(video_import_path)
        else [video_import_path]
    )

    for video_file_path in video_list:
        per_video_import_path = video_sample_path(import_path, video_file_path)
        if os.path.isdir(per_video_import_path):
            images = image_log.get_total_file_list(per_video_import_path)
            if images:
                answer = input(
                    f"The sample folder {per_video_import_path} already contains {len(images)} images.\nTo proceed, either DELETE the whole folder to restart the extraction (y), or skip the extraction (N)? [y/N] "
                )
                if answer in ["y", "Y"]:
                    shutil.rmtree(per_video_import_path)
        elif os.path.isfile(per_video_import_path):
            answer = input(
                f"The sample path {per_video_import_path} is found to be a file. To proceed, either DELETE it to restart the extraction (y), or skip the extraction (N)? [y/N] "
            )
            if answer in ["y", "Y"]:
                os.remove(per_video_import_path)

    for video_file_path in video_list:
        per_video_import_path = video_sample_path(import_path, video_file_path)
        if not os.path.exists(per_video_import_path):
            os.makedirs(per_video_import_path)
            extract_frames(
                video_file_path,
                per_video_import_path,
                video_sample_interval,
                video_duration_ratio,
            )


def extract_frames(
    video_file: str,
    import_path: str,
    video_sample_interval: float = 2.0,
    video_duration_ratio: float = 1.0,
) -> None:
    video_filename, ext = os.path.splitext(os.path.basename(video_file))
    command = [
        "ffmpeg",
        "-i",
        video_file,
        "-vf",
        f"fps=1/{video_sample_interval}",
        # video quality level
        "-qscale:v",
        "1",
        "-nostdin",
        f"{os.path.join(import_path, video_filename)}_%0{ZERO_PADDING}d.jpg",
    ]

    LOG.info(f"Extracting frames: {' '.join(command)}")
    try:
        subprocess.call(command)
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg not found. Please make sure it is installed in your PATH. See https://github.com/mapillary/mapillary_tools#video-support for instructions"
        )

    video_start_time = get_video_start_time(video_file)

    insert_video_frame_timestamp(
        video_filename,
        import_path,
        video_start_time,
        video_sample_interval,
        video_duration_ratio,
    )


def get_video_duration_and_end_time(
    video_file: str,
) -> T.Tuple[float, datetime.datetime]:
    probe = ffprobe.FFProbe(video_file)

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


def insert_video_frame_timestamp(
    video_filename: str,
    video_sampling_path: str,
    start_time: datetime.datetime,
    sample_interval: float = 2.0,
    duration_ratio: float = 1.0,
) -> None:
    frame_list = image_log.get_total_file_list(video_sampling_path)

    if not frame_list:
        LOG.warning("No video frames were extracted.")
        return

    video_frame_timestamps = timestamps_from_filename(
        video_filename, frame_list, start_time, sample_interval, duration_ratio
    )

    for image, timestamp in zip(frame_list, video_frame_timestamps):
        image_path = os.path.join(video_sampling_path, image)
        exif_edit = ExifEdit(image_path)
        exif_edit.add_date_time_original(timestamp)
        exif_edit.write()
