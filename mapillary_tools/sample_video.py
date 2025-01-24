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
from .geotag import geotag_videos_from_video
from .mp4 import mp4_sample_parser
from .process_geotag_properties import GeotagSource

LOG = logging.getLogger(__name__)


def _normalize_path(
    video_import_path: Path, skip_subfolders: bool
) -> T.Tuple[Path, T.List[Path]]:
    if video_import_path.is_dir():
        video_list = utils.find_videos(
            [video_import_path], skip_subfolders=skip_subfolders
        )
        video_dir = video_import_path.resolve()
        LOG.debug("Found %d videos in %s", len(video_list), video_dir)
    elif video_import_path.is_file():
        video_list = [video_import_path]
        video_dir = video_import_path.resolve().parent
    else:
        raise exceptions.MapillaryFileNotFoundError(
            f"Video file or directory not found: {video_import_path}"
        )
    assert video_dir.is_absolute(), f"video_dir must be absolute here: {str(video_dir)}"

    return video_dir, video_list


def xor(a: bool, b: bool):
    # xor https://stackoverflow.com/a/433161
    return bool(a) ^ bool(b)


def sample_video(
    video_import_path: Path,
    import_path: Path,
    # None if called from the sample_video command
    geotag_source: T.Optional[GeotagSource] = None,
    skip_subfolders=False,
    video_sample_distance=constants.VIDEO_SAMPLE_DISTANCE,
    video_sample_interval=constants.VIDEO_SAMPLE_INTERVAL,
    video_duration_ratio=constants.VIDEO_DURATION_RATIO,
    video_start_time: T.Optional[str] = None,
    skip_sample_errors: bool = False,
    rerun: bool = False,
) -> None:
    video_dir, video_list = _normalize_path(video_import_path, skip_subfolders)

    if not xor(0 <= video_sample_distance, 0 < video_sample_interval):
        raise exceptions.MapillaryBadParameterError(
            f"Expect either non-negative video_sample_distance or positive video_sample_interval but got {video_sample_distance} and {video_sample_interval} respectively"
        )

    video_start_time_dt: T.Optional[datetime.datetime] = None
    if video_start_time is not None:
        try:
            video_start_time_dt = types.map_capture_time_to_datetime(video_start_time)
        except ValueError as ex:
            raise exceptions.MapillaryBadParameterError(str(ex))

    if rerun:
        for video_path in video_list:
            # Example:
            # - import_path: mapillary_sampled_video_frames
            # - video_dir: foo/
            # - video_path: foo/bar/zzz.mp4
            # Then:
            # - sample_dir: mapillary_sampled_video_frames/bar/zzz.mp4/
            sample_dir = Path(import_path).joinpath(
                video_path.resolve().relative_to(video_dir)
            )
            LOG.info("Removing the sample directory %s", sample_dir)
            if sample_dir.is_dir():
                shutil.rmtree(sample_dir)
            elif sample_dir.is_file():
                os.remove(sample_dir)

    if geotag_source is None:
        geotag_source = "exif"

    # If it is not exif, then we use the legacy interval-based sample and geotag them in "process" for backward compatibility
    if geotag_source not in ["exif"]:
        if 0 <= video_sample_distance:
            raise exceptions.MapillaryBadParameterError(
                f'Geotagging from "{geotag_source}" works with the legacy interval-based sampling only. To switch back, rerun the command with "--video_sample_distance -1 --video_sample_interval 2"'
            )

    for video_path in video_list:
        # need to resolve video_path because video_dir might be absolute
        sample_dir = Path(import_path).joinpath(
            video_path.resolve().relative_to(video_dir)
        )
        if sample_dir.exists():
            LOG.warning(
                "Skip sampling video %s as it has been sampled in %s. Specify --rerun to resample it",
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
                assert 0 < video_sample_interval, (
                    "expect positive video_sample_interval but got {video_sample_interval}"
                )
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

        except Exception as ex:
            if skip_sample_errors:
                exc_info = LOG.getEffectiveLevel() <= logging.DEBUG
                LOG.warning(
                    "Skipping the error sampling %s: %s",
                    video_path,
                    str(ex),
                    exc_info=exc_info,
                )
            else:
                raise


@contextmanager
def wip_dir_context(wip_dir: Path, done_dir: Path, rename_timeout_sec: int = 10):
    assert wip_dir != done_dir, "should not be the same dir"
    shutil.rmtree(wip_dir, ignore_errors=True)
    os.makedirs(wip_dir)
    try:
        yield wip_dir
        shutil.rmtree(done_dir, ignore_errors=True)

        # Renames on Windows can occasionally fail and must be retried
        # https://bugs.python.org/issue46003
        if os.name == "nt":
            error = None
            renamed = False
            start_time = time.time()
            while not renamed and time.time() - start_time < rename_timeout_sec:
                try:
                    wip_dir.rename(done_dir)
                    renamed = True
                except Exception as e:
                    time.sleep(1)
                    error = e
            if not renamed and error is not None:
                raise error
        else:
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
            exif_edit.add_gps_datetime(timestamp)
            exif_edit.write()


def _within_track_time_range_buffered(points, t: float) -> bool:
    # apply 1ms buffer, which is MAPCaptureTime's precision
    start_point_time = points[0].time - 0.001
    end_point_time = points[-1].time + 0.001
    return start_point_time <= t <= end_point_time


def _sample_video_stream_by_distance(
    points: T.Sequence[geo.Point],
    video_track_parser: mp4_sample_parser.TrackBoxParser,
    sample_distance: float,
) -> T.Dict[int, T.Tuple[mp4_sample_parser.Sample, geo.Point]]:
    """
    Locate video frames along the track (points), then resample them by the minimal sample_distance, and return the sparse frames.
    """

    LOG.info("Extracting video samples")
    sorted_samples = list(video_track_parser.extract_samples())
    # we need sort sampels by composition time (CT) not the decoding offset (DT)
    # CT is the oder of videos streaming to audiences, as well as the order ffmpeg sampling
    sorted_samples.sort(key=lambda sample: sample.exact_composition_time)
    LOG.info("Found total %d video samples", len(sorted_samples))

    # interpolate sample points between the GPS track range (with 1ms buffer)
    LOG.info(
        "Interpolating video samples in the time range from %s to %s",
        points[0].time,
        points[-1].time,
    )
    interpolator = geo.Interpolator([points])
    interp_sample_points = [
        (
            frame_idx_0based,
            video_sample,
            interpolator.interpolate(video_sample.exact_composition_time),
        )
        for frame_idx_0based, video_sample in enumerate(sorted_samples)
        if _within_track_time_range_buffered(
            points, video_sample.exact_composition_time
        )
    ]
    LOG.info("Found total %d interpolated video samples", len(interp_sample_points))

    # select sample points by sample distance
    selected_interp_sample_points = list(
        geo.sample_points_by_distance(
            interp_sample_points,
            sample_distance,
            point_func=lambda x: x[2],
        )
    )
    LOG.info(
        "Selected %d video samples by the minimal sample distance %s",
        len(selected_interp_sample_points),
        sample_distance,
    )

    return {
        frame_idx_0based: (video_sample, interp)
        for frame_idx_0based, video_sample, interp in selected_interp_sample_points
    }


def _sample_single_video_by_distance(
    video_path: Path,
    sample_dir: Path,
    sample_distance: float,
    start_time: T.Optional[datetime.datetime] = None,
) -> None:
    ffmpeg = ffmpeglib.FFMPEG(constants.FFMPEG_PATH, constants.FFPROBE_PATH)

    probe = ffmpeglib.Probe(ffmpeg.probe_format_and_streams(video_path))

    if start_time is None:
        start_time = probe.probe_video_start_time()
        if start_time is None:
            raise exceptions.MapillaryVideoError(
                f"Unable to extract video start time from {video_path}"
            )

    LOG.info("Extracting video metdata")
    video_metadata = geotag_videos_from_video.GeotagVideosFromVideo.geotag_video(
        video_path
    )
    if isinstance(video_metadata, types.ErrorMetadata):
        LOG.warning(str(video_metadata.error))
        return
    assert video_metadata.points, "expect non-empty points"
    LOG.info("Found total %d GPS points", len(video_metadata.points))

    # find the video stream with maximum resolution
    video_stream = probe.probe_video_with_max_resolution()
    if not video_stream:
        LOG.warning("no video streams found from ffprobe")
        return

    LOG.info("Extracting video samples")
    video_stream_idx = video_stream["index"]
    moov_parser = mp4_sample_parser.MovieBoxParser.parse_file(video_path)
    video_track_parser = moov_parser.extract_track_at(video_stream_idx)
    sample_points_by_frame_idx = _sample_video_stream_by_distance(
        video_metadata.points, video_track_parser, sample_distance
    )
    sorted_sample_indices = sorted(sample_points_by_frame_idx.keys())

    with wip_dir_context(wip_sample_dir(sample_dir), sample_dir) as wip_dir:
        ffmpeg.extract_specified_frames(
            video_path,
            wip_dir,
            frame_indices=set(sorted_sample_indices),
            stream_idx=video_stream_idx,
        )

        frame_samples = ffmpeglib.sort_selected_samples(
            wip_dir, video_path, [video_stream_idx]
        )
        if len(frame_samples) != len(sorted_sample_indices):
            raise exceptions.MapillaryVideoError(
                f"Expect {len(sorted_sample_indices)} samples but extracted {len(frame_samples)} samples"
            )
        for idx, (frame_idx_1based, sample_paths) in enumerate(frame_samples):
            assert len(sample_paths) == 1, (
                "Expect 1 sample path at {frame_idx_1based} but got {sample_paths}"
            )
            if idx + 1 != frame_idx_1based:
                raise exceptions.MapillaryVideoError(
                    f"Expect {sample_paths[0]} to be {idx + 1}th sample but got {frame_idx_1based}"
                )

        for (_, sample_paths), sample_idx in zip(frame_samples, sorted_sample_indices):
            if sample_paths[0] is None:
                continue

            video_sample, interp = sample_points_by_frame_idx[sample_idx]
            assert interp.time == video_sample.exact_composition_time, (
                f"interpolated time {interp.time} should match the video sample time {video_sample.exact_composition_time}"
            )

            timestamp = start_time + datetime.timedelta(seconds=interp.time)
            exif_edit = ExifEdit(sample_paths[0])
            exif_edit.add_date_time_original(timestamp)
            exif_edit.add_gps_datetime(timestamp)
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
