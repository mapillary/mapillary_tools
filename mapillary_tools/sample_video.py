import typing as T
import datetime
import os
import shutil
import logging

from . import utils, ffmpeg, types, exceptions, constants
from .exif_write import ExifEdit

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT_2 = "%Y-%m-%dT%H:%M:%S.000000Z"
LOG = logging.getLogger(__name__)


def sample_video(
    video_import_path: str,
    import_path: str,
    skip_subfolders=False,
    video_sample_interval=constants.VIDEO_SAMPLE_INTERVAL,
    video_duration_ratio=constants.VIDEO_DURATION_RATIO,
    video_start_time: T.Optional[str] = None,
    skip_sample_errors: bool = False,
    rerun: bool = False,
) -> None:
    if os.path.isdir(video_import_path):
        video_list = utils.get_video_file_list(
            video_import_path, skip_subfolders, abs_path=True
        )
        video_dir = video_import_path
        LOG.debug(f"Found %d videos in %s", len(video_list), video_dir)
    elif os.path.isfile(video_import_path):
        video_list = [video_import_path]
        video_dir = os.path.dirname(video_import_path)
    else:
        raise exceptions.MapillaryFileNotFoundError(
            f"Video file or directory not found: {video_import_path}"
        )

    if rerun:
        for video_path in video_list:
            relpath = os.path.relpath(video_path, video_dir)
            video_sample_path = os.path.join(import_path, relpath)
            LOG.info(f"Removing the sample directory %s", video_sample_path)
            if os.path.isdir(video_sample_path):
                shutil.rmtree(video_sample_path)
            elif os.path.isfile(video_sample_path):
                os.remove(video_sample_path)

    video_start_time_dt: T.Optional[datetime.datetime] = None
    if video_start_time is not None:
        video_start_time_dt = types.map_capture_time_to_datetime(video_start_time)

    for video_path in video_list:
        relpath = os.path.relpath(video_path, video_dir)
        video_sample_path = os.path.join(import_path, relpath)
        if os.path.exists(video_sample_path):
            LOG.warning(
                f"Skip sampling video %s as it has been sampled in %s",
                os.path.basename(video_path),
                video_sample_path,
            )
            continue

        try:
            _sample_single_video(
                video_path,
                video_sample_path,
                sample_interval=video_sample_interval,
                duration_ratio=video_duration_ratio,
                start_time=video_start_time_dt,
            )
        except exceptions.MapillaryFFmpegNotFoundError:
            # fatal errors
            raise
        except Exception:
            if skip_sample_errors:
                LOG.warning(
                    f"Skipping the error sampling %s", video_path, exc_info=True
                )
            else:
                raise


def _sample_single_video(
    video_path: str,
    sample_path: str,
    sample_interval: float,
    duration_ratio: float,
    start_time: T.Optional[datetime.datetime] = None,
) -> None:
    # extract frames in the temporary folder and then rename it
    now = datetime.datetime.utcnow()
    tmp_sample_path = os.path.join(
        os.path.dirname(sample_path),
        f"{os.path.basename(sample_path)}.{os.getpid()}.{int(now.timestamp())}",
    )
    os.makedirs(tmp_sample_path)

    try:
        if start_time is None:
            duration, video_creation_time = extract_duration_and_creation_time(
                video_path
            )
            start_time = video_creation_time - datetime.timedelta(seconds=duration)
        ffmpeg.extract_frames(
            video_path,
            tmp_sample_path,
            sample_interval,
        )
        insert_video_frame_timestamp(
            os.path.basename(video_path),
            tmp_sample_path,
            start_time,
            sample_interval=sample_interval,
            duration_ratio=duration_ratio,
        )
        if os.path.isdir(sample_path):
            shutil.rmtree(sample_path)
        os.rename(tmp_sample_path, sample_path)
    finally:
        if os.path.isdir(tmp_sample_path):
            shutil.rmtree(tmp_sample_path)


def extract_duration_and_creation_time(
    video_path: str,
) -> T.Tuple[float, datetime.datetime]:
    streams = ffmpeg.probe_video_streams(video_path)
    if not streams:
        raise exceptions.MapillaryVideoError(f"No video streams found in {video_path}")

    # TODO: we should use the one with max resolution
    if 2 <= len(streams):
        LOG.warning(
            "Found %d video streams -- will use the first one",
            len(streams),
        )
    stream = streams[0]

    duration_str = stream.get("duration")
    try:
        # cast for type checking
        duration = float(T.cast(str, duration_str))
    except (TypeError, ValueError) as exc:
        raise exceptions.MapillaryVideoError(
            f"Failed to find video stream duration {duration_str} from video {video_path}"
        ) from exc
    LOG.debug("Extracted video duration: %s", duration)

    time_string = stream.get("tags", {}).get("creation_time")
    if time_string is None:
        raise exceptions.MapillaryVideoError(
            f"Failed to find video creation_time in {video_path}"
        )
    try:
        creation_time = datetime.datetime.strptime(time_string, TIME_FORMAT)
    except ValueError:
        try:
            creation_time = datetime.datetime.strptime(time_string, TIME_FORMAT_2)
        except ValueError:
            raise exceptions.MapillaryVideoError(
                f"Failed to parse {time_string} as {TIME_FORMAT} or {TIME_FORMAT_2}"
            )
    LOG.debug("Extracted video creation time: %s", creation_time)

    return duration, creation_time


def insert_video_frame_timestamp(
    video_basename: str,
    sample_path: str,
    start_time: datetime.datetime,
    sample_interval: float,
    duration_ratio: float,
) -> None:
    for image in utils.get_image_file_list(sample_path, abs_path=True):
        idx = ffmpeg.extract_idx_from_frame_filename(
            video_basename,
            os.path.basename(image),
        )
        if idx is None:
            LOG.warning(f"Unabele to find the sample index from %s", image)
            continue

        seconds = idx * sample_interval * duration_ratio
        timestamp = start_time + datetime.timedelta(seconds=seconds)
        exif_edit = ExifEdit(image)
        exif_edit.add_date_time_original(timestamp)
        exif_edit.write()
