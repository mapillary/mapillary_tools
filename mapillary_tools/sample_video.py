import datetime
import logging
import os
import shutil
import time
import typing as T
from contextlib import contextmanager
from pathlib import Path

from . import constants, exceptions, ffmpeg as ffmpeglib, geo, types, utils
from .exif_write import ExifEdit
from .geotag import mp4_sample_parser
from .process_geotag_properties import process_video

LOG = logging.getLogger(__name__)


def _normalize_path(
    video_import_path: Path, skip_subfolders: bool
) -> T.Tuple[Path, T.List[Path]]:
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

    return video_dir, video_list


def sample_video(
    video_import_path: Path,
    import_path: Path,
    skip_subfolders=False,
    video_sample_distance=constants.VIDEO_SAMPLE_DISTANCE,
    video_sample_interval=constants.VIDEO_SAMPLE_INTERVAL,
    video_duration_ratio=constants.VIDEO_DURATION_RATIO,
    video_start_time: T.Optional[str] = None,
    skip_sample_errors: bool = False,
    rerun: bool = False,
) -> None:
    video_dir, video_list = _normalize_path(video_import_path, skip_subfolders)

    if video_sample_interval < 0:
        raise exceptions.MapillaryBadParameterError(
            "expect non-negative video_sample_interval"
        )

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
                f"Skip sampling video %s as it has been sampled in %s. Specify --rerun for resampling all videos",
                video_path.name,
                sample_dir,
            )
            continue

        try:
            if 0 <= video_sample_distance:
                _sample_single_video_by_distance(
                    video_path,
                    sample_dir,
                    sample_distance=video_sample_distance,
                    start_time=video_start_time_dt,
                )
            else:
                _sample_single_video_by_interval(
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
        f".mly_ffmpeg_{sample_dir.name}_{pid}_{timestamp}"
    )


def _sample_single_video_by_interval(
    video_path: Path,
    sample_dir: Path,
    sample_interval: float,
    duration_ratio: float,
    start_time: T.Optional[datetime.datetime] = None,
) -> None:
    ffmpeg = ffmpeglib.FFMPEG(constants.FFMPEG_PATH, constants.FFPROBE_PATH)

    if start_time is None:
        start_time = ffmpeglib.Probe(
            ffmpeg.probe_format_and_streams(video_path)
        ).probe_video_start_time()
        if start_time is None:
            raise exceptions.MapillaryVideoError(
                f"Unable to extract video start time from {video_path}"
            )

    with wip_dir_context(wip_sample_dir(sample_dir), sample_dir) as wip_dir:
        ffmpeg.extract_frames(video_path, wip_dir, sample_interval)
        frame_samples = ffmpeglib.sort_selected_samples(wip_dir, video_path, [None])
        for frame_idx_1based, sample_paths in frame_samples:
            assert len(sample_paths) == 1
            if sample_paths[0] is None:
                continue
            # extract_frames() produces 1-based frame indices so we need to subtract 1 here
            seconds = (frame_idx_1based - 1) * sample_interval * duration_ratio
            timestamp = start_time + datetime.timedelta(seconds=seconds)
            exif_edit = ExifEdit(sample_paths[0])
            exif_edit.add_date_time_original(timestamp)
            exif_edit.write()


def _sample_single_video_by_distance(
    video_path: Path,
    sample_dir: Path,
    sample_distance: float,
    start_time: T.Optional[datetime.datetime] = None,
) -> None:
    ffmpeg = ffmpeglib.FFMPEG(constants.FFMPEG_PATH, constants.FFPROBE_PATH)

    probe: T.Optional[ffmpeglib.Probe] = None

    if start_time is None:
        if probe is None:
            probe = ffmpeglib.Probe(ffmpeg.probe_format_and_streams(video_path))
        start_time = probe.probe_video_start_time()
        if start_time is None:
            raise exceptions.MapillaryVideoError(
                f"Unable to extract video start time from {video_path}"
            )

    LOG.info("Extracting video metdata")
    video_metadata = process_video(
        video_path, {types.FileType.BLACKVUE, types.FileType.GOPRO, types.FileType.CAMM}
    )
    if isinstance(video_metadata, types.ErrorMetadata):
        LOG.warning(str(video_metadata.error))
        return
    assert video_metadata.points, "expect non-empty points"

    moov_parser = mp4_sample_parser.MovieBoxParser.parse_file(video_path)
    if probe is None:
        probe = ffmpeglib.Probe(ffmpeg.probe_format_and_streams(video_path))

    video_stream = probe.probe_video_with_max_resolution()

    if not video_stream:
        LOG.warning("no video streams found from ffprobe")
        return

    video_stream_idx = video_stream["index"]
    video_track_parser = moov_parser.parse_track_at(video_stream_idx)
    video_samples = list(video_track_parser.parse_samples())
    video_samples.sort(key=lambda sample: sample.composition_time_offset)
    LOG.info("Found total %d video samples", len(video_samples))

    interpolator = geo.Interpolator([video_metadata.points])
    interpolated_samples = (
        (
            frame_idx_0based,
            video_sample,
            interpolator.interpolate(video_sample.composition_time_offset),
        )
        for frame_idx_0based, video_sample in enumerate(video_samples)
    )
    selected_interpolated_samples = list(
        geo.sample_points_by_distance(
            interpolated_samples,
            sample_distance,
            point_func=lambda x: x[2],
        )
    )
    LOG.info(
        "Selected %d video samples by the minimal sample distance %s",
        len(selected_interpolated_samples),
        sample_distance,
    )

    selected_interpolated_samples_by_frame_idx = {
        frame_idx: (video_sample, interp)
        for frame_idx, video_sample, interp in selected_interpolated_samples
    }

    frame_indices = set(frame_idx for frame_idx, _, _ in selected_interpolated_samples)

    with wip_dir_context(wip_sample_dir(sample_dir), sample_dir) as wip_dir:
        ffmpeg.extract_specified_frames(
            video_path,
            wip_dir,
            frame_indices=frame_indices,
            video_stream_idx=video_stream_idx,
        )
        frame_samples = ffmpeglib.sort_selected_samples(
            wip_dir, video_path, [video_stream_idx]
        )
        # extract_specified_frames() produces 0-based frame indices
        for frame_idx_0based, sample_paths in frame_samples:
            assert len(sample_paths) == 1
            if sample_paths[0] is None:
                continue
            video_sample, interp = selected_interpolated_samples_by_frame_idx[
                frame_idx_0based
            ]
            seconds = video_sample.composition_time_offset
            timestamp = start_time + datetime.timedelta(seconds=seconds)
            exif_edit = ExifEdit(sample_paths[0])
            exif_edit.add_date_time_original(timestamp)
            exif_edit.add_lat_lon(interp.lat, interp.lon)
            if interp.alt is not None:
                exif_edit.add_altitude(interp.alt)
            if interp.angle is not None:
                exif_edit.add_direction(interp.angle)
            if video_metadata.make:
                exif_edit.add_make(video_metadata.make)
            if video_metadata.model:
                exif_edit.add_model(video_metadata.model)
            exif_edit.write()
