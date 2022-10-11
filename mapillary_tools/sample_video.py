import datetime
import logging
import os
import shutil
import time
import typing as T
from contextlib import contextmanager
from pathlib import Path

from . import constants, exceptions, ffmpeg as ffmpeglib, types, utils
from .exif_write import ExifEdit

LOG = logging.getLogger(__name__)


def sample_video(
    video_import_path: Path,
    import_path: Path,
    skip_subfolders=False,
    video_sample_interval=constants.VIDEO_SAMPLE_INTERVAL,
    video_duration_ratio=constants.VIDEO_DURATION_RATIO,
    video_start_time: T.Optional[str] = None,
    skip_sample_errors: bool = False,
    rerun: bool = False,
) -> None:
    if video_import_path.is_dir():
        video_list = utils.find_videos(
            [video_import_path], skip_subfolders=skip_subfolders
        )
        video_dir = video_import_path.resolve()
        LOG.debug(f"Found %d videos in %s", len(video_list), video_dir)
    elif video_import_path.is_file():
        video_list = [video_import_path]
        video_dir = video_import_path.resolve().parent
    else:
        raise exceptions.MapillaryFileNotFoundError(
            f"Video file or directory not found: {video_import_path}"
        )
    assert video_dir.is_absolute(), f"video_dir must be absolute here: {str(video_dir)}"

    video_start_time_dt: T.Optional[datetime.datetime] = None
    if video_start_time is not None:
        try:
            video_start_time_dt = types.map_capture_time_to_datetime(video_start_time)
        except ValueError as ex:
            raise exceptions.MapillaryBadParameterError(str(ex))

    if rerun:
        for video_path in video_list:
            # need to resolve video_path because video_dir might be absolute
            sample_dir = Path(import_path).joinpath(
                video_path.resolve().relative_to(video_dir)
            )
            LOG.info(f"Removing the sample directory %s", sample_dir)
            if sample_dir.is_dir():
                shutil.rmtree(sample_dir)
            elif sample_dir.is_file():
                os.remove(sample_dir)

    for video_path in video_list:
        # need to resolve video_path because video_dir might be absolute
        sample_dir = Path(import_path).joinpath(
            video_path.resolve().relative_to(video_dir)
        )
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
        except ffmpeglib.FFmpegNotFoundError as ex:
            # fatal error
            raise exceptions.MapillaryFFmpegNotFoundError(str(ex)) from ex

        except Exception:
            if skip_sample_errors:
                LOG.warning(
                    f"Skipping the error sampling %s", video_path, exc_info=True
                )
            else:
                raise


@contextmanager
def wip_dir_context(wip_dir: Path, done_dir: Path):
    assert wip_dir != done_dir, "should not be the same dir"
    shutil.rmtree(wip_dir, ignore_errors=True)
    os.makedirs(wip_dir)
    try:
        yield wip_dir
        shutil.rmtree(done_dir, ignore_errors=True)
        wip_dir.rename(done_dir)
    finally:
        shutil.rmtree(wip_dir, ignore_errors=True)


def wip_sample_dir(sample_dir: Path) -> Path:
    pid = os.getpid()
    timestamp = int(time.time())
    # prefix with .mly_ffmpeg_ to avoid samples being scanned by "mapillary_tools process"
    return sample_dir.resolve().parent.joinpath(
        f".mly_ffmpeg_{sample_dir.name}.{pid}.{timestamp}"
    )


def _sample_single_video(
    video_path: Path,
    sample_dir: Path,
    sample_interval: float,
    duration_ratio: float,
    start_time: T.Optional[datetime.datetime] = None,
) -> None:
    ffmpeg = ffmpeglib.FFMPEG(constants.FFMPEG_PATH, constants.FFPROBE_PATH)

    if start_time is None:
        start_time = ffmpeg.probe_video_start_time(video_path)
        if start_time is None:
            raise exceptions.MapillaryVideoError(
                f"Unable to extract video start time from {video_path}"
            )

    with wip_dir_context(wip_sample_dir(sample_dir), sample_dir) as wip_dir:
        ffmpeg.extract_frames(video_path, wip_dir, sample_interval)
        for idx, sample in ffmpeglib.list_samples(wip_dir, video_path):
            seconds = idx * sample_interval * duration_ratio
            timestamp = start_time + datetime.timedelta(seconds=seconds)
            exif_edit = ExifEdit(str(sample))
            exif_edit.add_date_time_original(timestamp)
            exif_edit.write()
