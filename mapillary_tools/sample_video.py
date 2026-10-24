# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import dataclasses
import datetime
import logging
import os
import re
import shutil
import statistics
import time
import typing as T
from contextlib import contextmanager
from pathlib import Path

import humanize

from . import (
    blackvue_parser,
    constants,
    exceptions,
    ffmpeg as ffmpeglib,
    geo,
    types,
    utils,
)
from .exif_write import ExifEdit
from .geotag import factory, geotag_images_from_gpx_file, geotag_images_from_nmea_file
from .geotag.geotag_images_from_gpx import check_within_track
from .geotag.options import (
    InterpolationOption,
    SourceOption,
    SourcePathOption,
    SourceType,
    VideoSyncOption,
)
from .geotag.video_extractors.gpx import (
    describe_gap,
    gps_seconds_apart,
    GPXVideoExtractor,
    track_gaps,
    VideoClock,
)
from .geotag.video_extractors.native import NativeVideoExtractor
from .geotag.video_extractors.nmea import NMEAVideoExtractor
from .mp4 import mp4_sample_parser, simple_mp4_parser as sparser
from .serializer.description import build_capture_time, parse_capture_time

LOG = logging.getLogger(__name__)


def _normalize_path(
    video_import_path: Path, skip_subfolders: bool
) -> tuple[Path, list[Path]]:
    if video_import_path.is_dir():
        # Sorted so that videos are sampled and reported in a stable order
        video_list = sorted(
            utils.find_videos([video_import_path], skip_subfolders=skip_subfolders)
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


def find_sample_dirs(
    video_import_path: Path, import_path: Path, skip_subfolders: bool = False
) -> list[Path]:
    """
    The folder in import_path that sample_video() samples each of the videos
    in video_import_path into
    """
    video_dir, video_list = _normalize_path(video_import_path, skip_subfolders)
    return [
        _sample_dir(import_path, video_dir, video_path) for video_path in video_list
    ]


def _sample_dir(import_path: Path, video_dir: Path, video_path: Path) -> Path:
    # need to resolve video_path because video_dir might be absolute
    return Path(import_path).joinpath(video_path.resolve().relative_to(video_dir))


def xor(a: bool, b: bool):
    # xor https://stackoverflow.com/a/433161
    return bool(a) ^ bool(b)


def _parse_geotag_options(
    geotag_source: list[str] | None,
    geotag_source_path: Path | None,
    video_geotag_source: list[str] | None,
    video_import_path: Path,
    video_sync: VideoSyncOption | None = None,
    interpolation: InterpolationOption | None = None,
) -> list[SourceOption]:
    """
    Resolve which sources distance sampling may take its positions from.

    Defaults to the video's own telemetry rather than to
    DEFAULT_GEOTAG_SOURCE_OPTIONS: the default chain continues on to
    exiftool_runtime, which reads the same telemetry through a parser that
    cannot see every field the noise filter rejects on, so routing sampling
    through it would accept tracks the native parser refuses.

    Every option carries video_sync and the interpolation options, for a GPX
    source to place its track where the geotagging stage will place the frames.
    As there, the interpolation options of a source override the global ones.
    """
    options = _parse_video_sources(
        geotag_source, geotag_source_path, video_geotag_source, video_import_path
    )

    for option in options:
        option.video_sync = video_sync
        if option.interpolation is None:
            option.interpolation = interpolation

    return options


def _parse_video_sources(
    geotag_source: list[str] | None,
    geotag_source_path: Path | None,
    video_geotag_source: list[str] | None,
    video_import_path: Path,
) -> list[SourceOption]:
    if not geotag_source and not video_geotag_source:
        return [SourceOption(SourceType.NATIVE)]

    options = factory.parse_source_options(
        geotag_source=geotag_source or [],
        video_geotag_source=video_geotag_source or [],
        geotag_source_path=geotag_source_path,
    )

    # Without an explicit path, every source gets the video import path, as
    # process_geotag_properties() gives it when geotagging the frames: that is
    # how exiftool_xml finds the XML files in the video directory. It does not
    # find a GPX beside the video, which the geotagging stage could not find
    # either; a GPX needs --geotag_source_path. A source's own pattern is kept:
    # it is resolved against each video here, and the import path would
    # override it (with the video itself, when the import path is a video)
    if geotag_source_path is None:
        for option in options:
            if option.source_path is None:
                if option.source is SourceType.EXIFTOOL_XML:
                    # The XML named after each video beside it, as in process
                    # and in the geotagging stage, or else the XMLs in the
                    # video import path
                    option.source_path = factory.exiftool_xml_default_source_path(
                        video_import_path
                    )
                else:
                    option.source_path = SourcePathOption(source_path=video_import_path)

    # exif and the legacy gopro/blackvue/camm sources have nothing to read a
    # video with; in video_process they are there to geotag the frames. Sample
    # by the sources that can read videos, or by the video's own GPS, as before,
    # if none of them can
    video_options = [option for option in options if factory.can_geotag_videos(option)]
    if not video_options:
        LOG.info(
            "None of the geotag sources %s can read GPS from videos. Sampling by the GPS in the videos",
            ",".join(option.source.value for option in options),
        )
        return [SourceOption(SourceType.NATIVE)]

    return video_options


def _parse_sample_sources(
    geotag_source: list[str] | None,
    geotag_source_path: Path | None,
    video_import_path: Path,
    interpolation: InterpolationOption,
) -> list[SourceOption] | None:
    """
    The sources that the geotagging stage of video_process geotags the samples
    by, as process_geotag_properties() picks them: those of --geotag_source,
    or, without it, the default sources, which read the position that sampling
    writes into a sample (an empty list here). None for the sample_video
    command, which cannot tell how its samples will be geotagged
    """
    if geotag_source is None:
        return None

    if not geotag_source:
        return []

    options = factory.parse_source_options(
        geotag_source=geotag_source,
        video_geotag_source=[],
        geotag_source_path=(
            video_import_path if geotag_source_path is None else geotag_source_path
        ),
    )
    for option in options:
        if option.interpolation is None:
            option.interpolation = interpolation
    return options


# Sources that geotag a sample by the time since the first sample of its video,
# at which they place the start of the video: the legacy sources and
# exiftool_xml, which geotag samples by the GPS of the videos they were taken
# from (see GeotagImagesFromVideo)
_FIRST_SAMPLE_SOURCES = frozenset(
    {SourceType.GOPRO, SourceType.BLACKVUE, SourceType.CAMM, SourceType.EXIFTOOL_XML}
)


def sample_video(
    video_import_path: Path,
    import_path: Path,
    # None if called from the sample_video command
    skip_subfolders=False,
    video_sample_distance=constants.VIDEO_SAMPLE_DISTANCE,
    video_sample_interval=constants.VIDEO_SAMPLE_INTERVAL,
    video_duration_ratio=constants.VIDEO_DURATION_RATIO,
    video_start_time: str | None = None,
    skip_sample_errors: bool = False,
    rerun: bool = False,
    # Absent when called from the sample_video command, which does not register
    # the process command's arguments
    geotag_source: list[str] | None = None,
    geotag_source_path: Path | None = None,
    video_geotag_source: list[str] | None = None,
    interpolation_offset_time: float = 0.0,
    interpolation_use_gpx_start_time: bool = False,
) -> None:
    video_dir, video_list = _normalize_path(video_import_path, skip_subfolders)

    if not xor(0 <= video_sample_distance, 0 < video_sample_interval):
        raise exceptions.MapillaryBadParameterError(
            f"Expect either non-negative video_sample_distance or positive video_sample_interval but got {video_sample_distance} and {video_sample_interval} respectively"
        )

    # Written as a negated comparison so that NaN is rejected too
    if not 0 < video_duration_ratio:
        raise exceptions.MapillaryBadParameterError(
            f"Expect a positive video_duration_ratio but got {video_duration_ratio}"
        )

    video_start_time_dt: datetime.datetime | None = None
    if video_start_time is not None:
        try:
            video_start_time_dt = parse_capture_time(video_start_time)
        except ValueError as ex:
            raise exceptions.MapillaryBadParameterError(str(ex))

    # Only a start time the user gave. A video needs one to place a GPX only if
    # it has no GPS clock, and then its start time would come from its creation
    # time, which cameras stamp at the start or at the end of the recording, some
    # in local time. Telling which takes evidence that a video may not carry, and
    # a GPX placed by a wrong guess is off by a whole video length or a time zone
    video_sync = VideoSyncOption(
        start_time=(
            video_start_time_dt.timestamp() if video_start_time_dt is not None else None
        ),
        duration_ratio=video_duration_ratio,
    )

    interpolation = InterpolationOption(
        offset_time=interpolation_offset_time,
        use_gpx_start_time=interpolation_use_gpx_start_time,
    )
    geotag_options = _parse_geotag_options(
        geotag_source,
        geotag_source_path,
        video_geotag_source,
        video_import_path,
        video_sync,
        interpolation,
    )
    # The sources that the geotagging stage of video_process geotags the
    # samples by, which tell which samples may be left out
    sample_sources = _parse_sample_sources(
        geotag_source, geotag_source_path, video_import_path, interpolation
    )

    if rerun:
        for video_path in video_list:
            # Example:
            # - import_path: mapillary_sampled_video_frames
            # - video_dir: foo/
            # - video_path: foo/bar/zzz.mp4
            # Then:
            # - sample_dir: mapillary_sampled_video_frames/bar/zzz.mp4/
            sample_dir = _sample_dir(import_path, video_dir, video_path)
            LOG.info("Removing the sample directory %s", sample_dir)
            if sample_dir.is_dir():
                shutil.rmtree(sample_dir)
            elif sample_dir.is_file():
                os.remove(sample_dir)

    if video_list:
        # Created even if no video samples, so that the process command that
        # follows in video_process finds an empty import path rather than none
        os.makedirs(import_path, exist_ok=True)

    num_sampled = 0
    num_already_sampled = 0
    failures: list[tuple[Path, Exception]] = []

    for video_path in video_list:
        sample_dir = _sample_dir(import_path, video_dir, video_path)
        if sample_dir.exists():
            LOG.warning(
                "Skip sampling video %s as it has been sampled in %s. Specify --rerun to resample it",
                video_path.name,
                sample_dir,
            )
            num_already_sampled += 1
            continue

        try:
            if 0 <= video_sample_distance:
                _sample_single_video_by_distance(
                    video_path,
                    sample_dir,
                    sample_distance=video_sample_distance,
                    start_time=video_start_time_dt,
                    geotag_options=geotag_options,
                    duration_ratio=video_duration_ratio,
                    sample_sources=sample_sources,
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
                    geotag_options=geotag_options,
                    video_sync=video_sync,
                    sample_sources=sample_sources,
                    single_video=len(video_list) == 1,
                )
        except ffmpeglib.FFmpegNotFoundError as ex:
            # fatal error
            raise exceptions.MapillaryFFmpegNotFoundError(str(ex)) from ex

        except Exception as ex:
            # Carry on with the other videos, as the process command does with
            # the other files, and fail after the summary. Log the reason now,
            # because unlike process, sampling writes no description file
            (LOG.warning if skip_sample_errors else LOG.error)(
                "Failed to sample %s: %s",
                video_path,
                str(ex),
                exc_info=LOG.isEnabledFor(logging.DEBUG),
            )
            failures.append((video_path, ex))

        else:
            num_sampled += 1

    _show_stats(
        len(video_list),
        num_sampled=num_sampled,
        num_already_sampled=num_already_sampled,
        failures=failures,
        skip_sample_errors=skip_sample_errors,
    )


def _show_stats(
    num_videos: int,
    num_sampled: int,
    num_already_sampled: int,
    failures: T.Sequence[tuple[Path, Exception]],
    skip_sample_errors: bool,
) -> None:
    LOG.info("==> Sample summary")
    LOG.info("%d videos found", num_videos)
    if num_sampled:
        LOG.info("\t%d sampled", num_sampled)
    if num_already_sampled:
        LOG.info("\t%d already sampled", num_already_sampled)

    failures_by_type: dict[type[Exception], int] = {}
    for _, ex in failures:
        failures_by_type[type(ex)] = failures_by_type.get(type(ex), 0) + 1

    for error_type, count in failures_by_type.items():
        (LOG.warning if skip_sample_errors else LOG.error)(
            "\t%d %s", count, error_type.__name__
        )

    if failures and not skip_sample_errors:
        raise exceptions.MapillaryVideoSampleError(
            f"Failed to sample {len(failures)} videos. To skip these errors, specify --skip_sample_errors"
        )


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


# GPS clocks that report a time before this have never been set: GoPro writes
# 2000-01-01 until it gets its first fix, for example
_MIN_PLAUSIBLE_START_TIME = datetime.datetime(
    2010, 1, 1, tzinfo=datetime.timezone.utc
).timestamp()

# Leave room for the clock of the machine running this to be behind
_MAX_FUTURE_START_TIME_SECONDS = 24 * 3600

# How many GPS timestamps to take the median of, so that a single bad one cannot
# shift the start time: the Labpano PanoX V2 can record a stale first fix,
# seconds older than the rest. Only the first few are used because in timelapses
# the video clock runs slower than the GPS clock, so the two drift apart
_GPS_CLOCK_SAMPLES = 5

# Cameras known to stamp the creation time at the end of the recording, as
# lowercase (make, model) from the container tags. BlackVue is not listed
# because it does not write those tags: blackvue_parser.is_blackvue detects it
_END_STAMPING_CAMERAS = {
    ("ricoh", "ricoh theta x"),
    ("labpano", "panox v2"),
}

# A date and time in a file name, for example 20230512_101530 (BlackVue,
# Insta360) or 2023_0512_101530 (Viofo), in the camera's local time
_FILENAME_TIME_RE = re.compile(
    r"(?<!\d)(20\d\d)[-_]?(\d\d)[-_]?(\d\d)[-_T]?(\d\d)[-_]?(\d\d)[-_]?(\d\d)(?!\d)"
)

# UTC offsets range from -12 to +14 hours in multiples of 15 minutes
_MAX_UTC_OFFSET_SECONDS = 14 * 3600
_UTC_OFFSET_GRANULARITY_SECONDS = 15 * 60

# Cameras do not name the file at exactly the moment they stamp the creation
# time: Insta360's are about 10 seconds apart
_FILENAME_TIME_TOLERANCE_SECONDS = 15


def _gps_clock_start_time(
    points: T.Sequence[geo.Point],
) -> datetime.datetime | None:
    """
    Map the absolute GPS timestamps at the start of a track back to the video's time 0.

    Point times are relative to the start of the video, so subtracting one from
    its own absolute timestamp gives the wall clock at which the video started.
    Timestamps outside the plausible range are skipped.
    """
    max_start_time = time.time() + _MAX_FUTURE_START_TIME_SECONDS

    start_times: list[float] = []
    for point in points:
        unix_time = point.get_unix_time()
        if unix_time is None:
            continue
        start_time = unix_time - point.time
        # Written as a negated range check so that NaN is skipped too
        if not (_MIN_PLAUSIBLE_START_TIME <= start_time <= max_start_time):
            continue
        start_times.append(start_time)
        if len(start_times) >= _GPS_CLOCK_SAMPLES:
            break

    if not start_times:
        return None

    return datetime.datetime.fromtimestamp(
        statistics.median(start_times), tz=datetime.timezone.utc
    )


def _read_telemetry(video_path: Path) -> T.Sequence[geo.Point]:
    """
    Read the GPS points of the video's own telemetry, or none if it has none
    """
    try:
        return NativeVideoExtractor(video_path).extract().points
    except exceptions.MapillaryDescriptionError as ex:
        LOG.debug("No video telemetry to read the clock from: %s", ex)
    except Exception as ex:
        # Telemetry is only one way to tell when the frames were captured, so
        # a video whose telemetry fails to parse must still be sampled
        LOG.warning(
            "Unable to read the telemetry of %s: %s",
            video_path.name,
            ex,
            exc_info=LOG.isEnabledFor(logging.DEBUG),
        )
    return []


def _telemetry_clock(
    video_path: Path, telemetry_points: T.Sequence[geo.Point]
) -> VideoClock | None:
    """
    The video's own GPS clock, or None if it has none. It runs more than 1 GPS
    second per video second if the video is a timelapse
    """
    clock = GPXVideoExtractor._read_video_clock(telemetry_points)
    if clock is None:
        return None

    if clock.rate != 1.0:
        LOG.info(
            "The GPS clock in %s runs %.3g times faster than the video",
            video_path.name,
            clock.rate,
        )
    return clock


def _parse_filename_time(video_path: Path) -> datetime.datetime | None:
    for match in _FILENAME_TIME_RE.finditer(video_path.stem):
        year, month, day, hour, minute, second = (int(g) for g in match.groups())
        try:
            return datetime.datetime(
                year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc
            )
        except ValueError:
            continue

    return None


def _as_utc(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _is_same_time_in_another_time_zone(
    a: datetime.datetime, b: datetime.datetime
) -> bool:
    """
    Tell whether two times could be the same moment, one of them possibly in
    local time labelled as UTC
    """
    delta = abs((_as_utc(a) - _as_utc(b)).total_seconds())
    if _MAX_UTC_OFFSET_SECONDS + _FILENAME_TIME_TOLERANCE_SECONDS < delta:
        return False
    remainder = delta % _UTC_OFFSET_GRANULARITY_SECONDS
    return (
        min(remainder, _UTC_OFFSET_GRANULARITY_SECONDS - remainder)
        <= _FILENAME_TIME_TOLERANCE_SECONDS
    )


def _is_end_stamping_camera(video_path: Path, probe: ffmpeglib.Probe) -> bool:
    make = probe.probe_format_tag("make")
    model = probe.probe_format_tag("model")
    if make is not None and model is not None:
        if (make.strip().lower(), model.strip().lower()) in _END_STAMPING_CAMERAS:
            return True

    try:
        with video_path.open("rb") as fp:
            return blackvue_parser.is_blackvue(fp)
    except Exception as ex:
        LOG.debug("Unable to tell whether %s is a BlackVue video: %s", video_path, ex)
        return False


def _creation_time_to_start_time(
    video_path: Path, probe: ffmpeglib.Probe
) -> datetime.datetime | None:
    """
    Determine the wall clock time at which a video started recording from the
    creation time in its metadata.

    Cameras disagree on what the creation time marks. Many stamp the end of the
    recording: BlackVue, Viofo, Vantrue and most other dashcams, the Ricoh Theta
    X and the Labpano PanoX V2. Others stamp the start: Sony, Insta360 and the
    dashcam in the bug report that motivated reading this at all. Nothing in the
    metadata says which, so look for evidence: a camera known to stamp the end,
    or a time in the file name that matches only one of the two. Without any,
    assume the start and warn about the alternative.
    """
    creation_time = probe.probe_video_creation_time()
    if creation_time is None:
        return None

    duration = probe.probe_video_duration()
    if duration is None:
        LOG.warning(
            "Unable to read the duration of %s, so assuming its creation time %s marks the start of the recording",
            video_path.name,
            creation_time,
        )
        return creation_time

    start_time_if_end_stamped = creation_time - datetime.timedelta(seconds=duration)

    if _is_end_stamping_camera(video_path, probe):
        return start_time_if_end_stamped

    filename_time = _parse_filename_time(video_path)
    if filename_time is not None:
        matches_start = _is_same_time_in_another_time_zone(filename_time, creation_time)
        matches_end = _is_same_time_in_another_time_zone(
            filename_time, start_time_if_end_stamped
        )
        if matches_end and not matches_start:
            return start_time_if_end_stamped
        if matches_start and not matches_end:
            return creation_time

    LOG.warning(
        "Assuming the creation time %s of %s marks the start of the recording. "
        "If the camera stamps the end instead, as most dashcams do, the recording started %.1f seconds earlier: "
        "specify --video_start_time %s to use that",
        creation_time,
        video_path.name,
        duration,
        build_capture_time(start_time_if_end_stamped),
    )
    return creation_time


def _extract_video_start_time(
    video_path: Path,
    probe: ffmpeglib.Probe,
    telemetry_points: T.Sequence[geo.Point],
) -> datetime.datetime | None:
    """
    Determine the wall clock time at which a video started recording.

    A video's own telemetry is the better clock: it is absolute UTC, so it is
    immune both to cameras that stamp the container's creation time at the end
    of the recording and to cameras that stamp it in local time (GoPro). Fall
    back to the creation time when there is no telemetry to sync against, which
    is the case for the plain MP4s that get geotagged from a GPX.
    """
    start_time = _gps_clock_start_time(telemetry_points)
    if start_time is not None:
        return start_time

    return _creation_time_to_start_time(video_path, probe)


# The sources that place a track file on a video, by the extractor that reads it
_TRACK_FILE_EXTRACTORS: dict[SourceType, type[GPXVideoExtractor]] = {
    SourceType.GPX: GPXVideoExtractor,
    SourceType.NMEA: NMEAVideoExtractor,
}


def _check_gpx_start_by_interval(
    video_path: Path,
    geotag_options: T.Sequence[SourceOption],
    video_sync: VideoSyncOption,
) -> None:
    """
    Check the GPX (or NMEA) tracks that --interpolation_use_gpx_start_time says
    started with a video without a GPS clock, as distance sampling does. The
    geotagging stage puts the first frame at the start of the track and the
    others at --video_duration_ratio, so a track that runs on long after the
    video was not recorded for it alone, or needs the ratio.
    """
    for option in geotag_options:
        extractor_class = _TRACK_FILE_EXTRACTORS.get(option.source)
        if extractor_class is None or option.source_path is None:
            continue
        if option.interpolation is None or not option.interpolation.use_gpx_start_time:
            continue
        gpx_path = option.source_path.resolve(video_path)
        if not gpx_path.is_file():
            continue
        extractor = extractor_class(
            video_path,
            gpx_path,
            video_sync=video_sync,
            interpolation=option.interpolation,
        )
        if _gpx_sync_reads_a_clock(extractor):
            continue
        gpx_points = extractor._read_gpx_points()
        if gpx_points:
            extractor._check_given_start(gpx_points, video_sync.duration_ratio)


def _gpx_sync_reads_a_clock(extractor: GPXVideoExtractor) -> bool:
    """
    Whether GPX sync, in distance sampling and process, reads a GPS clock from
    the video. It reads one from GPS rejected as noise too, which interval
    sampling has no telemetry from, and syncs the GPX at that clock's pace
    """
    try:
        native_video_metadata, _ = extractor._extract_native_video_metadata()
    except exceptions.MapillaryVideoGPSUnusableError:
        return False
    except Exception:
        # Telemetry that fails to parse is warned about by _read_telemetry(),
        # and must not stop the video from being sampled
        return False
    return extractor._read_video_clock(native_video_metadata.points) is not None


def _gpx_sync_clock(
    video_path: Path, geotag_options: T.Sequence[SourceOption]
) -> VideoClock | None:
    """
    The clock that GPX sync, in distance sampling and process, places the
    track of the first GPX (or NMEA) source by along a video whose GPS was
    rejected as noise, which interval sampling has no telemetry from. None if
    it places the track as for a video without a GPS clock.
    """
    for option in geotag_options:
        extractor_class = _TRACK_FILE_EXTRACTORS.get(option.source)
        if extractor_class is None or option.source_path is None:
            continue
        gpx_path = option.source_path.resolve(video_path)
        if not gpx_path.is_file():
            continue
        extractor = extractor_class(
            video_path,
            gpx_path,
            video_sync=option.video_sync,
            interpolation=option.interpolation,
        )
        try:
            native_video_metadata, noisy = extractor._extract_native_video_metadata()
            gpx_points = extractor._read_gpx_points()
        except Exception as ex:
            # The geotagging stage reports what keeps it from reading the
            # GPS of the video or the GPX
            LOG.debug("No GPX sync clock for %s: %s", video_path.name, ex)
            return None
        if not noisy:
            return None
        video_clock = extractor._read_video_clock(native_video_metadata.points)
        return extractor._sync_clock(video_clock, gpx_points, noisy)

    return None


def _probe_video(ffmpeg: ffmpeglib.FFMPEG, video_path: Path) -> ffmpeglib.Probe:
    """
    Probe the streams of a video with ffprobe. A video that ffprobe fails to
    read because it has no movie box (moov), such as an MP4 cut short before
    it, is invalid, as process reports it
    """
    try:
        return ffmpeglib.Probe(ffmpeg.probe_format_and_streams(video_path))
    except ffmpeglib.FFmpegCalledProcessError as ex:
        try:
            with video_path.open("rb") as fp:
                sparser.parse_box_data_firstx(fp, [b"moov"])
        except sparser.BoxNotFoundError as box_ex:
            raise exceptions.MapillaryInvalidVideoError(
                f"Invalid video: {box_ex}"
            ) from ex
        except (OSError, sparser.ParsingError):
            pass
        raise ex


def _interval_stream_specifier(probe: ffmpeglib.Probe) -> str:
    """
    The video stream to sample by interval: the one with the highest
    resolution, as for sampling by distance. ffmpeg numbers the frames of all
    the streams it samples in one sequence, so with two (a GoPro MAX .360 video
    has two) each frame would be numbered, and stamped, as if twice as late.
    A video with a single video stream is sampled as "v", which names its
    samples as it always has.
    """
    video_streams = probe.probe_video_streams()
    if len(video_streams) <= 1:
        return "v"

    video_stream = probe.probe_video_with_max_resolution()
    assert video_stream is not None
    return str(video_stream["index"])


def _sample_single_video_by_interval(
    video_path: Path,
    sample_dir: Path,
    sample_interval: float,
    duration_ratio: float,
    start_time: datetime.datetime | None = None,
    geotag_options: T.Sequence[SourceOption] = (),
    video_sync: VideoSyncOption | None = None,
    # How the samples are geotagged (see _parse_sample_sources())
    sample_sources: T.Sequence[SourceOption] | None = None,
    # Whether the video is the only one sampled
    single_video: bool = True,
) -> None:
    ffmpeg = ffmpeglib.FFMPEG(constants.FFMPEG_PATH, constants.FFPROBE_PATH)

    telemetry_points = _read_telemetry(video_path)

    # Frames are stamped with their capture times, which a timelapse packs
    # several seconds of into each second of video: by the video's own GPS
    # clock, as GPX sync places a GPX and distance samples are stamped, and for
    # a video without a GPS clock, at --video_duration_ratio
    clock = _telemetry_clock(video_path, telemetry_points)
    # GPS rejected as noise gives no telemetry, but GPX sync reads its clock,
    # and the frames are stamped by it, where GPX sync places them along the
    # GPX, so that the geotagging stage finds them there
    if clock is None:
        clock = _gpx_sync_clock(video_path, geotag_options)
    if clock is None:
        rate = duration_ratio
    else:
        rate = clock.rate
        if duration_ratio != 1.0:
            LOG.warning(
                "Ignoring --video_duration_ratio %g for %s, whose own GPS clock runs at %.3gx",
                duration_ratio,
                video_path.name,
                clock.rate,
            )

    if clock is None and video_sync is not None:
        _check_gpx_start_by_interval(video_path, geotag_options, video_sync)

    probe = _probe_video(ffmpeg, video_path)

    if start_time is None:
        if clock is not None:
            start_time = datetime.datetime.fromtimestamp(
                clock.to_unix_time(0.0), tz=datetime.timezone.utc
            )
        else:
            start_time = _extract_video_start_time(video_path, probe, telemetry_points)
        if start_time is None:
            raise exceptions.MapillaryVideoError(
                f"Unable to extract video start time from {video_path}"
            )

    # Located along the video's own GPS track, or the GPX (or NMEA) track of
    # --video_geotag_source as GPX sync placed it on the video, as distance
    # samples are
    track_read = _read_track_for_interval_samples(video_path, geotag_options)
    track = track_read[0] if track_read is not None else None
    # The gaps of a track placed from a file, outside it (see track_gaps())
    track_gaps_: list[tuple[geo.Point, geo.Point]] = []
    track_from_file = track_read is not None and _placed_from_a_file(track_read[1])
    if track_read is not None and track_from_file:
        track = _start_at_the_first_sample(video_path, *track_read)
        track_gaps_ = track_gaps(track.points, constants.MAX_GPX_GAP_SECONDS, rate)
    interpolator = geo.Interpolator([track.points]) if track is not None else None
    # Or located by the geotagging stage along a GPX (or NMEA) track, by their
    # capture times
    file_track = (
        _read_file_track_for_interval_samples(sample_sources) if track is None else None
    )

    stream_specifier = _interval_stream_specifier(probe)
    # The stream sampled, whether it is the only one or not
    video_stream = probe.probe_video_with_max_resolution()

    with wip_dir_context(wip_sample_dir(sample_dir), sample_dir) as wip_dir:
        ffmpeg.extract_frames_by_interval(
            video_path,
            wip_dir,
            sample_interval,
            stream_specifier=stream_specifier,
            sample_aspect_ratio=(
                video_stream.get("sample_aspect_ratio") if video_stream else None
            ),
        )
        frame_samples = ffmpeglib.FFMPEG.sort_selected_samples(
            wip_dir, video_path, selected_stream_specifiers=[stream_specifier]
        )

        # (path, video time, capture time) of each sample
        samples: list[tuple[Path, float, datetime.datetime]] = []
        for frame_idx_1based, sample_paths in frame_samples:
            assert len(sample_paths) == 1
            if sample_paths[0] is None:
                continue
            # extract_frames() produces 1-based frame indices so we need to subtract 1 here
            video_time = (frame_idx_1based - 1) * sample_interval
            timestamp = start_time + datetime.timedelta(seconds=video_time * rate)
            samples.append((sample_paths[0], video_time, timestamp))

        if track is not None and track_from_file:
            covered = [
                _covers(track.points, track_gaps_, video_time)
                for _, video_time, _ in samples
            ]
            # Unless the geotagging stage may geotag the samples by the GPS of
            # their video instead
            left_out = (
                set()
                if any(
                    option.source in _FIRST_SAMPLE_SOURCES
                    for option in sample_sources or []
                )
                else _samples_to_leave_out(covered, keep_leading=False)
            )
            track_range = (
                _track_time(track.points[0], start_time, rate),
                _track_time(track.points[-1], start_time, rate),
            )
        elif track is not None:
            covered = [
                _within_track_time_range_buffered(track.points, video_time)
                for _, video_time, _ in samples
            ]
            left_out = _samples_to_leave_out(
                covered,
                keep_leading=_samples_placed_by_the_first(sample_sources),
            )
            track_range = (
                start_time + datetime.timedelta(seconds=track.points[0].time * rate),
                start_time + datetime.timedelta(seconds=track.points[-1].time * rate),
            )
        elif file_track is not None:
            covered = file_track.covers(
                [timestamp.timestamp() for _, _, timestamp in samples]
            )
            left_out = (
                set()
                if file_track.placed_by_the_first and not single_video
                else _samples_to_leave_out(
                    covered, keep_leading=file_track.placed_by_the_first
                )
            )
            track_range = (
                datetime.datetime.fromtimestamp(
                    file_track.points[0].time, tz=datetime.timezone.utc
                ),
                datetime.datetime.fromtimestamp(
                    file_track.points[-1].time, tz=datetime.timezone.utc
                ),
            )
        else:
            covered = [False] * len(samples)
            left_out = set()

        if left_out:
            LOG.warning(
                "%d of the %d samples of %s %s outside its GPS track (%s to %s) and %s left out",
                len(left_out),
                len(samples),
                video_path.name,
                "falls" if len(left_out) == 1 else "fall",
                track_range[0].isoformat(),
                track_range[1].isoformat(),
                "was" if len(left_out) == 1 else "were",
            )

        for idx, (sample_path, video_time, timestamp) in enumerate(samples):
            if idx in left_out:
                sample_path.unlink()
                continue
            interp = (
                interpolator.interpolate(video_time)
                if track is not None and interpolator is not None and covered[idx]
                else None
            )
            if interp is not None and track_from_file:
                # Stamped with the time of the track where the sample is, as
                # distance samples of a track from a file are
                timestamp = _track_time(interp, timestamp, 1.0)
            exif_edit = ExifEdit(sample_path)
            exif_edit.add_date_time_original(timestamp)
            exif_edit.add_gps_datetime(timestamp)
            if track is not None and interp is not None:
                _add_position(exif_edit, track, interp)
            exif_edit.write()


def _placed_from_a_file(track_source: SourceOption | None) -> bool:
    """
    Whether the track of a video was placed on it from a GPX (or NMEA) file:
    the source that read it, of those tried in turn, is such a file, whatever
    the other sources are
    """
    return (
        track_source is not None and track_source.source in factory.EXTERNAL_GPS_SOURCES
    )


def _placed_from_a_video_file(
    track_source: SourceOption | None, geotag_options: T.Sequence[SourceOption]
) -> bool:
    """
    Whether the track that distance samples are sampled along is placed on
    the video from a GPX (or NMEA) file of --video_geotag_source, as interval
    samples are located along it (see _read_track_for_interval_samples()). A
    file of --geotag_source geotags the samples too, which the geotagging stage
    places along its track by their capture times
    """
    return _placed_from_a_file(track_source) and not any(
        option.source in factory.EXTERNAL_GPS_SOURCES
        and (option.filetypes is None or types.FileType.IMAGE in option.filetypes)
        for option in geotag_options
    )


def _file_track_gaps(
    points: T.Sequence[geo.Point],
) -> list[tuple[geo.Point, geo.Point]]:
    """
    The gaps of a track placed on the video from a GPX (or NMEA) file, outside
    it as in the geotagging stage (see track_gaps()): between consecutive
    points more than constants.MAX_GPX_GAP_SECONDS apart by the GPS times they
    keep (see gps_seconds_apart()), which a timelapse packs into less video
    """
    gaps: list[tuple[geo.Point, geo.Point]] = []
    for before, after in geo.pairwise(points):
        before_time, after_time = before.get_unix_time(), after.get_unix_time()
        if (
            before_time is not None
            and after_time is not None
            and constants.MAX_GPX_GAP_SECONDS < gps_seconds_apart(before, after)
        ):
            gaps.append((before, after))
    return gaps


def _describe_file_track_gap(before: geo.Point, after: geo.Point) -> str:
    """Describe a gap that _file_track_gaps() found, by its GPS times"""
    before_time, after_time = before.get_unix_time(), after.get_unix_time()
    assert before_time is not None and after_time is not None
    return describe_gap(before, after, before_time, after_time)


def _start_at_the_first_sample(
    video_path: Path,
    track: types.VideoMetadata,
    option: SourceOption,
) -> types.VideoMetadata:
    """
    A track that --interpolation_use_gpx_start_time starts with the video,
    moved to start at the first interval sample: GPX sync starts it at the
    composition time of the first frame, at which distance sampling reads the
    first frame, and interval sampling stamps the samples from time 0, which
    ffmpeg cuts the first one at. **option** is the source that placed it
    """
    if option.interpolation is None or not option.interpolation.use_gpx_start_time:
        return track
    # As GPX sync starts it
    start = GPXVideoExtractor(
        video_path,
        video_path,
        video_sync=option.video_sync,
        interpolation=option.interpolation,
    )._gpx_start_video_time()
    if not start:
        return track
    return dataclasses.replace(
        track,
        points=[dataclasses.replace(p, time=p.time - start) for p in track.points],
    )


def _covers(
    points: T.Sequence[geo.Point],
    gaps: T.Sequence[tuple[geo.Point, geo.Point]],
    video_time: float,
) -> bool:
    """
    Whether a track placed on the video covers a sample at **video_time**, as
    the geotagging stage tells whether a GPX track covers an image
    """
    try:
        check_within_track(video_time, points, gaps)
    except exceptions.MapillaryOutsideGPXTrackError:
        return False
    return True


def _track_time(
    point: geo.Point, start_time: datetime.datetime, rate: float
) -> datetime.datetime:
    """
    The time of a point of a track placed on the video: its own GPS time, or,
    without one, that of its video time from **start_time** at **rate**
    """
    unix_time = point.get_unix_time()
    if unix_time is None:
        return start_time + datetime.timedelta(seconds=point.time * rate)
    return datetime.datetime.fromtimestamp(unix_time, tz=datetime.timezone.utc)


def _samples_to_leave_out(covered: T.Sequence[bool], keep_leading: bool) -> set[int]:
    """
    The indices of the interval samples to leave out, given which of them the
    track that geotags them covers: those it does not, so that they do not
    fail geotagging. If it covers none of them, none, so that the samples
    fail rather than leave the video out without a word. With
    **keep_leading**, not those before the first sample it covers either:
    the geotagging stage places the samples by the time since the first one
    (see _samples_placed_by_the_first())

    >>> sorted(_samples_to_leave_out([False, True, True, False], keep_leading=False))
    [0, 3]
    >>> sorted(_samples_to_leave_out([False, True, False, True, False], keep_leading=True))
    [2, 4]
    >>> _samples_to_leave_out([False, False], keep_leading=False)
    set()
    """
    if not any(covered):
        return set()
    first = covered.index(True)
    return {
        idx
        for idx, is_covered in enumerate(covered)
        if not is_covered and (first < idx or not keep_leading)
    }


def _samples_placed_by_the_first(
    sample_sources: T.Sequence[SourceOption] | None,
) -> bool:
    """
    Whether the geotagging stage may place the samples of a video by the time
    since its first sample, so that leaving out the samples before the track
    starts would misplace the others: the sources of _FIRST_SAMPLE_SOURCES,
    and a GPX (or NMEA) track that --interpolation_use_gpx_start_time starts
    at the first sample. The sample_video command cannot tell which sources
    will geotag its samples

    >>> _samples_placed_by_the_first(None)
    True
    >>> _samples_placed_by_the_first([])
    False
    >>> _samples_placed_by_the_first([SourceOption(SourceType.GOPRO)])
    True
    >>> _samples_placed_by_the_first([SourceOption(SourceType.EXIF)])
    False
    """
    if sample_sources is None:
        return True
    return any(
        option.source in _FIRST_SAMPLE_SOURCES
        or (
            option.source in factory.EXTERNAL_GPS_SOURCES
            and option.interpolation is not None
            and option.interpolation.use_gpx_start_time
        )
        for option in sample_sources
    )


@dataclasses.dataclass(frozen=True)
class _FileTrack:
    """
    A GPX (or NMEA) track that the geotagging stage locates samples along by
    their capture times, as GeotagImagesFromGPX locates images
    """

    # Sorted by time
    points: T.Sequence[geo.Point]
    gaps: T.Sequence[tuple[geo.Point, geo.Point]]
    # --interpolation_offset_time
    offset_time: float
    # --interpolation_use_gpx_start_time: the track starts at the first sample
    placed_by_the_first: bool

    def covers(self, capture_times: T.Sequence[float]) -> list[bool]:
        """
        Whether the track covers each sample of a video, given their capture
        times, in order
        """
        offset = self.offset_time
        if self.placed_by_the_first and capture_times:
            offset += self.points[0].time - capture_times[0]

        covered = []
        for capture_time in capture_times:
            try:
                check_within_track(capture_time + offset, self.points, self.gaps)
            except exceptions.MapillaryOutsideGPXTrackError:
                covered.append(False)
            else:
                covered.append(True)
        return covered


def _read_file_track_for_interval_samples(
    sample_sources: T.Sequence[SourceOption] | None,
) -> _FileTrack | None:
    """
    The GPX (or NMEA) track that the geotagging stage locates the interval
    samples along by their capture times: that of the first such source of
    --geotag_source, which geotags images. None if there is none, if it cannot
    be read (the geotagging stage reports why), or if another source may
    geotag the samples it misses: one that geotags them by the GPS of their
    video, or another track file
    """
    if not sample_sources:
        return None

    track_sources = [
        option
        for option in sample_sources
        if option.source in factory.EXTERNAL_GPS_SOURCES
        and (option.filetypes is None or types.FileType.IMAGE in option.filetypes)
    ]
    if len(track_sources) != 1 or any(
        option.source in _FIRST_SAMPLE_SOURCES for option in sample_sources
    ):
        return None

    option = track_sources[0]
    if option.source_path is None or option.source_path.source_path is None:
        return None

    try:
        if option.source is SourceType.GPX:
            points = geotag_images_from_gpx_file._read_gpx_points(
                option.source_path.source_path
            )
        else:
            points = geotag_images_from_nmea_file._read_nmea_points(
                option.source_path.source_path
            )
    except exceptions.MapillaryInvalidGPXError:
        return None

    sorted_points = sorted(points, key=lambda point: point.time)
    interpolation = option.interpolation
    return _FileTrack(
        points=sorted_points,
        gaps=track_gaps(sorted_points, constants.MAX_GPX_GAP_SECONDS),
        offset_time=0.0 if interpolation is None else interpolation.offset_time,
        placed_by_the_first=(
            interpolation is not None and interpolation.use_gpx_start_time
        ),
    )


def _read_track_for_interval_samples(
    video_path: Path, geotag_options: T.Sequence[SourceOption]
) -> tuple[types.VideoMetadata, SourceOption] | None:
    """
    The track that the interval samples of a video are located along, in
    video time, as distance samples are, and the source that read it: the
    video's own GPS track, or that of a GPX (or NMEA) file of
    --video_geotag_source as GPX sync placed it on the video. None to leave
    their positions to the geotagging stage: that places them along the track
    of a GPX (or NMEA) file of --geotag_source, which geotags images, by their
    capture times
    """
    if any(
        option.source in factory.EXTERNAL_GPS_SOURCES
        and (option.filetypes is None or types.FileType.IMAGE in option.filetypes)
        for option in geotag_options
    ):
        return None

    # Through the factory with the same sources as distance sampling, which
    # reads the video's own GPS by default (see _parse_geotag_options())
    video_metadata, track_source = _read_video_track(
        video_path, geotag_options or [SourceOption(SourceType.NATIVE)]
    )
    if isinstance(video_metadata, types.ErrorMetadata):
        LOG.warning(
            "The samples of %s are not geotagged, as no GPS track was read from it: %s",
            video_path.name,
            video_metadata.error,
        )
        return None

    assert isinstance(video_metadata, types.VideoMetadata), (
        f"expect VideoMetadata but got {type(video_metadata).__name__}"
    )
    if not video_metadata.points:
        LOG.warning(
            "The samples of %s are not geotagged, as it has no GPS points",
            video_path.name,
        )
        return None

    assert track_source is not None, "expect the source of a video's track"
    return video_metadata, track_source


def _read_video_track(
    video_path: Path, geotag_options: T.Sequence[SourceOption]
) -> tuple[types.MetadataOrError, SourceOption | None]:
    """
    The track of a video, read through the factory by the first of
    **geotag_options** that geotags it, as in the geotagging stage, and that
    source (None if none does). The video is read in this process rather than
    in a pool of its own, so that a GPX (or NMEA) file that geotags several
    videos is read once
    """
    sources: dict[Path, SourceOption] = {}
    video_metadatas = factory.process(
        [video_path],
        [dataclasses.replace(option, num_processes=0) for option in geotag_options],
        sources=sources,
    )
    # Every option can read videos (see _parse_geotag_options()), so process()
    # returns metadata for the video even if all of them fail
    assert len(video_metadatas) == 1, "expect 1 video metadata"
    return video_metadatas[0], sources.get(video_path)


def _add_position(
    exif_edit: ExifEdit, video_metadata: types.VideoMetadata, point: geo.Point
) -> None:
    """
    Write the position of a sample, and the camera of the video it was cut
    from, as distance sampling writes them
    """
    exif_edit.add_lat_lon(point.lat, point.lon)
    if point.alt is not None:
        exif_edit.add_altitude(point.alt)
    if point.angle is not None:
        exif_edit.add_direction(point.angle)
    if video_metadata.make:
        exif_edit.add_make(video_metadata.make)
    if video_metadata.model:
        exif_edit.add_model(video_metadata.model)


def _within_track_time_range_buffered(points, t: float) -> bool:
    # apply 1ms buffer, which is MAPCaptureTime's precision
    start_point_time = points[0].time - 0.001
    end_point_time = points[-1].time + 0.001
    return start_point_time <= t <= end_point_time


def _sample_video_stream_by_distance(
    points: T.Sequence[geo.Point],
    video_track_parser: mp4_sample_parser.TrackBoxParser,
    sample_distance: float,
    # The gaps of the track, outside it, whose frames are left out (see
    # _file_track_gaps()), and the name of the video, to warn of them
    gaps: T.Sequence[tuple[geo.Point, geo.Point]] = (),
    video_name: str = "the video",
) -> dict[int, tuple[mp4_sample_parser.Sample, geo.Point]]:
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
    if gaps:
        # Clamped to the ends of the track, past which frames are kept by 1 ms,
        # so that only its gaps leave frames out
        covered = [
            _covers(
                points,
                gaps,
                min(
                    max(video_sample.exact_composition_time, points[0].time),
                    points[-1].time,
                ),
            )
            for _, video_sample, _ in interp_sample_points
        ]
        times_in_gaps = [
            video_sample.exact_composition_time
            for (_, video_sample, _), c in zip(interp_sample_points, covered)
            if not c
        ]
        if times_in_gaps:
            gaps_left_out = [
                (before, after)
                for before, after in gaps
                if any(before.time < t < after.time for t in times_in_gaps)
            ]
            LOG.warning(
                "%d %s of %s %s in %s of its GPS track and %s left out: %s",
                len(times_in_gaps),
                "frame" if len(times_in_gaps) == 1 else "frames",
                video_name,
                "falls" if len(times_in_gaps) == 1 else "fall",
                "a gap" if len(gaps_left_out) == 1 else f"{len(gaps_left_out)} gaps",
                "was" if len(times_in_gaps) == 1 else "were",
                "; ".join(
                    _describe_file_track_gap(before, after)
                    for before, after in gaps_left_out
                ),
            )
            interp_sample_points = [
                x for x, c in zip(interp_sample_points, covered) if c
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


def _describe_track_time_range(points: T.Sequence[geo.Point]) -> str:
    """
    >>> p = lambda t: geo.Point(time=t, lat=0, lon=0, alt=None, angle=None)
    >>> _describe_track_time_range([p(-7200), p(-3600)])
    'which ends an hour before the video starts'
    >>> _describe_track_time_range([p(600), p(700)])
    'which starts 10 minutes after the video starts'
    >>> _describe_track_time_range([p(0.01), p(0.02)])
    'which covers 0.010 to 0.020 seconds of the video'
    """
    start = min(p.time for p in points)
    end = max(p.time for p in points)

    if end < 0:
        return f"which ends {humanize.naturaldelta(-end)} before the video starts"

    if 1 <= start:
        return f"which starts {humanize.naturaldelta(start)} after the video starts"

    return f"which covers {start:.3f} to {end:.3f} seconds of the video"


def _warn_of_options_the_clock_overrides(
    video_path: Path,
    points: T.Sequence[geo.Point],
    sample_points: T.Sequence[geo.Point],
    duration_ratio: float,
    start_time: datetime.datetime | None,
) -> None:
    """
    Warn of --video_duration_ratio and --video_start_time, which distance
    sampling ignores for a video sampled by its own GPS, if it has a GPS clock:
    the clock paces the video, and the frames are stamped with the GPS
    timestamps of the points they are sampled at (**sample_points**). A frame
    sampled where the track has no timestamp is stamped from the start time.
    """
    if duration_ratio == 1.0 and start_time is None:
        return

    clock = GPXVideoExtractor._read_video_clock(points)
    if clock is None:
        return

    if duration_ratio != 1.0:
        LOG.warning(
            "Ignoring --video_duration_ratio %g for %s, whose own GPS clock runs at %.3gx",
            duration_ratio,
            video_path.name,
            clock.rate,
        )

    if start_time is not None and all(
        p.get_unix_time() is not None for p in sample_points
    ):
        LOG.warning(
            "Ignoring --video_start_time %s for %s, which has a GPS clock of its own",
            build_capture_time(start_time),
            video_path.name,
        )


def _sample_single_video_by_distance(
    video_path: Path,
    sample_dir: Path,
    sample_distance: float,
    start_time: datetime.datetime | None = None,
    geotag_options: T.Sequence[SourceOption] | None = None,
    duration_ratio: float = 1.0,
    # How the samples are geotagged (see _parse_sample_sources())
    sample_sources: T.Sequence[SourceOption] | None = None,
) -> None:
    if geotag_options is None:
        geotag_options = [SourceOption(SourceType.NATIVE)]

    ffmpeg = ffmpeglib.FFMPEG(constants.FFMPEG_PATH, constants.FFPROBE_PATH)

    probe = _probe_video(ffmpeg, video_path)

    LOG.info("Extracting video metdata")

    # Go through the factory rather than reading the video's own telemetry
    # directly, so that --geotag_source is honoured here as well: a GPX is the
    # documented answer for a camera whose embedded GPS is unusable, and
    # distance sampling needs positions just as much as geotagging does
    video_metadata, track_source = _read_video_track(video_path, geotag_options)

    # Distance sampling needs positions to decide which frames to cut, so
    # failing to read them is a failed sample, not something to carry on past.
    # Warning and returning left the caller with a success exit code, an empty
    # (or missing) sample directory and nothing to upload. Raised as is, so
    # that the sample summary counts it by its own type
    if isinstance(video_metadata, types.ErrorMetadata):
        raise video_metadata.error

    # Only a video path was passed in, so only video metadata can come back
    assert isinstance(video_metadata, types.VideoMetadata), (
        f"expect VideoMetadata but got {type(video_metadata).__name__}"
    )

    if not video_metadata.points:
        raise exceptions.MapillaryVideoGPSNotFoundError("No GPS points found")

    LOG.info("Found total %d GPS points", len(video_metadata.points))

    # find the video stream with maximum resolution
    video_stream = probe.probe_video_with_max_resolution()
    if not video_stream:
        raise exceptions.MapillaryVideoError(
            f"No video streams found in {video_path} by ffprobe"
        )

    LOG.info("Extracting video samples")
    video_stream_idx = video_stream["index"]
    moov_parser = mp4_sample_parser.MovieBoxParser.parse_file(video_path)
    video_track_parser = moov_parser.extract_track_at(video_stream_idx)
    # A track placed on the video from a GPX (or NMEA) file of
    # --video_geotag_source is not interpolated across its gaps, outside it as
    # in the geotagging stage: the frames in them are left out, as interval
    # samples are. Unless the geotagging stage may geotag the samples by the
    # GPS of their video instead
    gaps = (
        _file_track_gaps(video_metadata.points)
        if _placed_from_a_video_file(track_source, geotag_options)
        and not any(
            option.source in _FIRST_SAMPLE_SOURCES for option in sample_sources or []
        )
        else []
    )
    sample_points_by_frame_idx = _sample_video_stream_by_distance(
        video_metadata.points,
        video_track_parser,
        sample_distance,
        gaps,
        video_path.name,
    )
    # A track that misses the video, such as a GPX from another trip or one
    # placed by a wrong --video_start_time, selects no frames, and an empty
    # sample directory would pass for success
    if not sample_points_by_frame_idx:
        raise exceptions.MapillaryVideoError(
            "none of its frames falls within its GPS track, "
            + _describe_track_time_range(video_metadata.points)
        )
    sorted_sample_indices = sorted(sample_points_by_frame_idx.keys())

    # The GPS timestamps of the track, which frames are stamped within
    track_unix_times = [
        unix_time
        for unix_time in (p.get_unix_time() for p in video_metadata.points)
        if unix_time is not None
    ]
    first_unix_time = min(track_unix_times, default=None)
    last_unix_time = max(track_unix_times, default=None)

    # Read from the video itself, a track with a GPS clock of its own paces the
    # video, and its clock stamps the frames, as interval samples are. A GPX
    # source warns of the options that its sync ignores itself, and its sync
    # placed the track along the video's clock already: its timestamps stamp
    # the frames as they are
    track_clock: VideoClock | None = None
    if not any(
        option.source in factory.EXTERNAL_GPS_SOURCES for option in geotag_options
    ):
        _warn_of_options_the_clock_overrides(
            video_path,
            video_metadata.points,
            [interp for _, interp in sample_points_by_frame_idx.values()],
            duration_ratio,
            start_time,
        )
        track_clock = GPXVideoExtractor._read_video_clock(video_metadata.points)
        if track_clock is not None:
            # Frames are stamped by the clock within its times at the first and
            # last points: not within their timestamps, which jitter about the
            # clock, so that the frames stamped past the last timestamp, with
            # positions up to the last point, do not all get that timestamp
            first_unix_time = track_clock.to_unix_time(video_metadata.points[0].time)
            last_unix_time = track_clock.to_unix_time(video_metadata.points[-1].time)

    # Frames stamped by the clock, or at points with an absolute timestamp,
    # are timestamped below, so only the others need the start time
    if (
        start_time is None
        and track_clock is None
        and any(
            interp.get_unix_time() is None
            for _, interp in sample_points_by_frame_idx.values()
        )
    ):
        start_time = _gps_clock_start_time(video_metadata.points)
        if start_time is None:
            start_time = _creation_time_to_start_time(video_path, probe)
        if start_time is None:
            raise exceptions.MapillaryVideoError(
                f"Unable to extract video start time from {video_path}"
            )

    with wip_dir_context(wip_sample_dir(sample_dir), sample_dir) as wip_dir:
        ffmpeg.extract_specified_frames(
            video_path,
            wip_dir,
            frame_indices=set(sorted_sample_indices),
            stream_specifier=str(video_stream_idx),
            sample_aspect_ratio=video_stream.get("sample_aspect_ratio"),
        )

        frame_samples = ffmpeglib.FFMPEG.sort_selected_samples(
            wip_dir, video_path, selected_stream_specifiers=[str(video_stream_idx)]
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

            gps_unix_time = (
                interp.get_unix_time()
                if track_clock is None
                else track_clock.to_unix_time(interp.time)
            )
            if gps_unix_time is not None:
                assert first_unix_time is not None and last_unix_time is not None
                # Frames up to 1 ms of video past either end of the track are
                # kept, and their timestamps extrapolated. In a timelapse, 1 ms
                # of video spans several ms of GPS time, and the geotagging
                # stage allows a frame only 1 ms past the end of a GPX track
                gps_unix_time = min(max(gps_unix_time, first_unix_time), last_unix_time)
                timestamp = datetime.datetime.fromtimestamp(
                    gps_unix_time, tz=datetime.timezone.utc
                )
            else:
                assert start_time is not None
                timestamp = start_time + datetime.timedelta(seconds=interp.time)
            exif_edit = ExifEdit(sample_paths[0])
            exif_edit.add_date_time_original(timestamp)
            exif_edit.add_gps_datetime(timestamp)
            _add_position(exif_edit, video_metadata, interp)
            exif_edit.write()
