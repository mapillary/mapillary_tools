import typing as T
import datetime
import os
import shutil
import logging

from . import utils, ffmpeg, types, exceptions
from .exif_write import ExifEdit

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT_2 = "%Y-%m-%dT%H:%M:%S.000000Z"
LOG = logging.getLogger(__name__)


def sample_video(
    video_import_path: str,
    import_path: str,
    skip_subfolders=False,
    video_sample_interval=2.0,
    video_start_time: T.Optional[str] = None,
    video_duration_ratio=1.0,
    skip_sample_errors: bool = False,
    rerun: bool = False,
) -> None:
    if not os.path.exists(video_import_path):
        raise exceptions.MapillaryFileNotFoundError(
            f"Video file or directory not found: {video_import_path}"
        )

    if os.path.isdir(video_import_path):
        video_list = utils.get_video_file_list(
            video_import_path, skip_subfolders, abs_path=True
        )
        video_dir = video_import_path
    else:
        video_list = [video_import_path]
        video_dir = os.path.dirname(video_import_path)

    LOG.debug(f"Found {len(video_list)} videos in {video_import_path}")

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
        video_start_time_dt: T.Optional[datetime.datetime] = None
        if video_start_time is not None:
            video_start_time_dt = types.map_capture_time_to_datetime(video_start_time)

        relpath = os.path.relpath(video_path, video_dir)
        video_sample_path = os.path.join(import_path, relpath)
        if os.path.exists(video_sample_path):
            LOG.warning(
                f"Skip sampling video {os.path.basename(video_path)} as it has been sampled in {video_sample_path}"
            )
            continue

        # extract frames in the temporary folder and then rename it
        now = datetime.datetime.utcnow()
        video_sample_path_temporary = os.path.join(
            os.path.dirname(video_sample_path),
            f"{os.path.basename(video_sample_path)}.{os.getpid()}.{int(now.timestamp())}",
        )
        os.makedirs(video_sample_path_temporary)
        try:
            ffmpeg.extract_frames(
                video_path,
                video_sample_path_temporary,
                video_sample_interval,
            )
            if video_start_time_dt is None:
                video_start_time_dt = extract_video_start_time(video_path)
            insert_video_frame_timestamp(
                os.path.basename(video_path),
                video_sample_path_temporary,
                video_start_time_dt,
                video_sample_interval,
                video_duration_ratio,
            )
        except (
            exceptions.MapillaryFileNotFoundError,
            exceptions.MapillaryFFmpegNotFoundError,
        ):
            raise
        except Exception:
            if skip_sample_errors:
                LOG.warning(f"Skipping the error sampling {video_path}", exc_info=True)
            else:
                raise
        else:
            LOG.debug(f"Renaming {video_sample_path_temporary} to {video_sample_path}")
            try:
                os.rename(video_sample_path_temporary, video_sample_path)
            except IOError:
                # video_sample_path might have been created by another process during the sampling
                LOG.warning(
                    f"Skip the error renaming {video_sample_path} to {video_sample_path}",
                    exc_info=True,
                )
        finally:
            if os.path.isdir(video_sample_path_temporary):
                shutil.rmtree(video_sample_path_temporary)


def extract_video_start_time(video_path: str) -> datetime.datetime:
    streams = ffmpeg.probe_video_streams(video_path)
    if not streams:
        raise exceptions.MapillaryVideoError(
            f"Failed to find video streams in {video_path}"
        )

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
        video_end_time = datetime.datetime.strptime(time_string, TIME_FORMAT)
    except ValueError:
        try:
            video_end_time = datetime.datetime.strptime(time_string, TIME_FORMAT_2)
        except ValueError:
            raise exceptions.MapillaryVideoError(
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
    for image in utils.get_image_file_list(video_sampling_path, abs_path=True):
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
