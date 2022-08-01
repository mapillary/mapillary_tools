import typing as T
import datetime
import os
import shutil
import logging
from pathlib import Path

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
        video_list = [
            Path(path)
            for path in utils.get_video_file_list(
                video_import_path, skip_subfolders, abs_path=True
            )
        ]
        video_dir = Path(video_import_path)
        LOG.debug(f"Found %d videos in %s", len(video_list), video_dir)
    elif os.path.isfile(video_import_path):
        video_list = [Path(video_import_path)]
        video_dir = Path(video_import_path).parent
    else:
        raise exceptions.MapillaryFileNotFoundError(
            f"Video file or directory not found: {video_import_path}"
        )

    video_start_time_dt: T.Optional[datetime.datetime] = None
    if video_start_time is not None:
        try:
            video_start_time_dt = types.map_capture_time_to_datetime(video_start_time)
        except ValueError as ex:
            raise exceptions.MapillaryBadParameterError(str(ex))

    if rerun:
        for video_path in video_list:
            sample_dir = Path(import_path).joinpath(video_path.relative_to(video_dir))
            LOG.info(f"Removing the sample directory %s", sample_dir)
            if sample_dir.is_dir():
                shutil.rmtree(sample_dir)
            elif sample_dir.is_file():
                os.remove(sample_dir)

    for video_path in video_list:
        sample_dir = Path(import_path).joinpath(video_path.relative_to(video_dir))
        if sample_dir.exists():
            LOG.warning(
                f"Skip sampling video %s as it has been sampled in %s",
                video_path.name,
                sample_dir,
            )
            continue

        try:
            _sample_single_video(
                video_path,
                sample_dir,
                sample_interval=video_sample_interval,
                duration_ratio=video_duration_ratio,
                start_time=video_start_time_dt,
            )
        except ffmpeg.FFmpegNotFoundError as ex:
            # fatal error
            raise exceptions.MapillaryFFmpegNotFoundError(str(ex)) from ex

        except Exception:
            if skip_sample_errors:
                LOG.warning(
                    f"Skipping the error sampling %s", video_path, exc_info=True
                )
            else:
                raise


def _sample_single_video(
    video_path: Path,
    sample_dir: Path,
    sample_interval: float,
    duration_ratio: float,
    start_time: T.Optional[datetime.datetime] = None,
) -> None:
    if start_time is None:
        duration, video_creation_time = extract_duration_and_creation_time(video_path)
        start_time = video_creation_time - datetime.timedelta(seconds=duration)

    for idx, sample in ffmpeg.sample_video_wip(video_path, sample_dir, sample_interval):
        seconds = idx * sample_interval * duration_ratio
        timestamp = start_time + datetime.timedelta(seconds=seconds)
        exif_edit = ExifEdit(str(sample))
        exif_edit.add_date_time_original(timestamp)
        exif_edit.write()


def extract_duration_and_creation_time(
    video_path: Path,
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
