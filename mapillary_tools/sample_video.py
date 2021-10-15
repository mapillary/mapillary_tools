import datetime
import os
import shutil
import logging

from . import image_log, ffmpeg
from .exif_write import ExifEdit

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT_2 = "%Y-%m-%dT%H:%M:%S.000000Z"
LOG = logging.getLogger(__name__)


def sample_video(
    video_import_path: str,
    import_path: str,
    skip_subfolders=False,
    video_sample_interval=2.0,
    video_start_time=None,
    video_duration_ratio=1.0,
    rerun: bool = False,
) -> None:
    if not os.path.exists(video_import_path):
        raise RuntimeError(f'Error, video path "{video_import_path}" does not exist')

    if os.path.isdir(video_import_path):
        video_list = image_log.get_video_file_list(
            video_import_path, skip_subfolders, abs_path=True
        )
        video_dir = video_import_path
    else:
        video_list = [video_import_path]
        video_dir = os.path.dirname(video_import_path)

    if rerun:
        for video_path in video_list:
            relpath = os.path.relpath(video_path, video_dir)
            video_sample_path = os.path.join(import_path, relpath)
            LOG.info(f"Removing the sample directory {video_sample_path}")
            if os.path.isdir(video_sample_path):
                shutil.rmtree(video_sample_path)
            elif os.path.isfile(video_sample_path):
                os.remove(video_sample_path)

    for video_path in video_list:
        relpath = os.path.relpath(video_path, video_dir)
        video_sample_path = os.path.join(import_path, relpath)
        if os.path.exists(video_sample_path):
            LOG.warning(
                f"Skip video {os.path.basename(video_path)} as it has been sampled in {video_sample_path}"
            )
        else:
            os.makedirs(video_sample_path)

            ffmpeg.extract_frames(
                video_path,
                video_sample_path,
                video_sample_interval,
            )

            video_start_time = extract_video_start_time(video_path)

            insert_video_frame_timestamp(
                os.path.basename(video_path),
                video_sample_path,
                video_start_time,
                video_sample_interval,
                video_duration_ratio,
            )


def extract_video_start_time(video_path: str) -> datetime.datetime:
    streams = ffmpeg.probe_video_streams(video_path)
    if not streams:
        raise RuntimeError(f"Failed to find video streams in {video_path}")

    if 2 <= len(streams):
        LOG.warning(
            "Found more than one (%s) video streams -- will use the first stream",
            len(streams),
        )

    stream = streams[0]

    duration_str = stream["duration"]
    try:
        duration = float(duration_str)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Failed to find video stream duration {duration_str} from video {video_path}"
        ) from exc

    LOG.debug("Extracted video duration: %s", duration)

    time_string = stream.get("tags", {}).get("creation_time")
    if time_string is None:
        raise RuntimeError(f"Failed to find video creation_time in {video_path}")

    try:
        video_end_time = datetime.datetime.strptime(time_string, TIME_FORMAT)
    except ValueError:
        try:
            video_end_time = datetime.datetime.strptime(time_string, TIME_FORMAT_2)
        except ValueError:
            raise RuntimeError(
                f"Failed to parse {time_string} as {TIME_FORMAT} or {TIME_FORMAT_2}"
            )

    LOG.debug("Extracted video end time (creation time): %s", video_end_time)

    return video_end_time - datetime.timedelta(seconds=duration)


def insert_video_frame_timestamp(
    video_basename: str,
    video_sampling_path: str,
    start_time: datetime.datetime,
    sample_interval: float = 2.0,
    duration_ratio: float = 1.0,
) -> None:
    for image in image_log.get_total_file_list(video_sampling_path, abs_path=True):
        idx = ffmpeg.extract_idx_from_frame_filename(
            video_basename,
            os.path.basename(image),
        )
        if idx is None:
            LOG.warning(f"Unabele to extract timestamp from the sample image {image}")
            continue

        seconds = idx * sample_interval * duration_ratio
        timestamp = start_time + datetime.timedelta(seconds=seconds)
        exif_edit = ExifEdit(image)
        exif_edit.add_date_time_original(timestamp)
        exif_edit.write()
