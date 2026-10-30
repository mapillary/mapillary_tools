# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import os
import shutil
import subprocess
import time
import typing as T
from pathlib import Path
from unittest import mock

import py.path
import pynmea2
import pytest
from mapillary_tools import (
    exceptions,
    exif_read,
    ffmpeg as ffmpeglib,
    geo,
    sample_video,
    telemetry,
)
from mapillary_tools.geotag.options import (
    InterpolationOption,
    SourceOption,
    SourceType,
    VideoSyncOption,
)
from mapillary_tools.geotag.video_extractors import gpx as gpx_extractor
from mapillary_tools.mp4 import construct_mp4_parser as cparser, mp4_sample_parser
from mapillary_tools.serializer import description
from mapillary_tools.types import describe_error_metadata, FileType, VideoMetadata

_PWD = Path(os.path.dirname(os.path.abspath(__file__)))

# The creation time of the hello.mp4 probe fixture, which is where videos
# without their own GPS clock get their start time from
PROBE_START_TIME = datetime.datetime(
    2021, 8, 10, 14, 38, 6, tzinfo=datetime.timezone.utc
)


# ---------------------------------------------------------------------------
# Interval-based sampling tests (using MOCK_FFMPEG)
# ---------------------------------------------------------------------------


class MOCK_FFMPEG(ffmpeglib.FFMPEG):
    def extract_frames_by_interval(
        self,
        video_path: Path,
        sample_path: Path,
        video_sample_interval: float,
        stream_specifier: int | str = "v",
        sample_aspect_ratio: str | None = None,
    ):
        probe = self.probe_format_and_streams(video_path)
        video_streams = [
            s for s in probe.get("streams", []) if s.get("codec_type") == "video"
        ]
        duration = float(video_streams[0]["duration"])
        video_basename_no_ext, _ = os.path.splitext(os.path.basename(video_path))
        frame_path_prefix = os.path.join(sample_path, video_basename_no_ext)
        src = os.path.join(_PWD, "data/test_exif.jpg")
        for idx in range(0, int(duration / video_sample_interval)):
            sample = f"{frame_path_prefix}_{stream_specifier}_{idx + 1:06d}.jpg"
            shutil.copyfile(src, sample)

    def probe_format_and_streams(self, video_path: Path) -> ffmpeglib.ProbeOutput:
        with open(video_path) as fp:
            return json.load(fp)


@pytest.fixture
def setup_mock(monkeypatch):
    monkeypatch.setattr(ffmpeglib, "FFMPEG", MOCK_FFMPEG)


def _validate_interval(
    samples: T.Sequence[Path], video_start_time, seconds_per_sample: float = 2
):
    assert len(samples), "expect samples but got none"
    for idx, sample in enumerate(sorted(samples)):
        assert sample.name == f"hello_v_{idx + 1:06d}.jpg"
        exif = exif_read.ExifRead(sample)
        expected_dt = video_start_time + datetime.timedelta(
            seconds=seconds_per_sample * idx
        )
        assert exif.extract_capture_time() == expected_dt


def test_sample_video(tmpdir: py.path.local, setup_mock):
    root = _PWD.joinpath("data/mock_sample_video")
    video_dir = root.joinpath("videos")
    sample_dir = tmpdir.mkdir("sampled_video_frames")
    sample_video.sample_video(
        video_dir,
        Path(sample_dir),
        video_sample_distance=-1,
        video_sample_interval=2,
        rerun=True,
    )
    samples = sample_dir.join("hello.mp4").listdir()
    _validate_interval([Path(s) for s in samples], PROBE_START_TIME)


def test_sample_single_video(tmpdir: py.path.local, setup_mock):
    root = _PWD.joinpath("data/mock_sample_video")
    video_path = root.joinpath("videos", "hello.mp4")
    sample_dir = tmpdir.mkdir("sampled_video_frames")
    sample_video.sample_video(
        video_path,
        Path(sample_dir),
        video_sample_distance=-1,
        video_sample_interval=2,
        rerun=True,
    )
    samples = sample_dir.join("hello.mp4").listdir()
    _validate_interval([Path(s) for s in samples], PROBE_START_TIME)


def test_sample_video_with_start_time(tmpdir: py.path.local, setup_mock):
    root = _PWD.joinpath("data/mock_sample_video")
    video_dir = root.joinpath("videos")
    sample_dir = tmpdir.mkdir("sampled_video_frames")
    video_start_time_str = "2020_08_10_14_37_05_023"
    video_start_time = description.parse_capture_time(video_start_time_str)
    sample_video.sample_video(
        video_dir,
        Path(sample_dir),
        video_start_time=video_start_time_str,
        video_sample_distance=-1,
        video_sample_interval=2,
        rerun=True,
    )
    samples = sample_dir.join("hello.mp4").listdir()
    _validate_interval([Path(s) for s in samples], video_start_time)


def test_sample_the_video_stream_with_the_highest_resolution(
    tmpdir: py.path.local, setup_mock
):
    """
    By interval as by distance: ffmpeg would number the frames of two streams
    in one sequence, and they would be stamped as if twice as late.
    """
    root = _PWD.joinpath("data/mock_sample_video")
    probe = json.loads(root.joinpath("videos", "hello.mp4").read_text())
    [video_stream] = [s for s in probe["streams"] if s["codec_type"] == "video"]
    probe["streams"].append({**video_stream, "index": 2, "width": 5760})
    video_dir = Path(tmpdir.mkdir("videos"))
    video_dir.joinpath("hello.mp4").write_text(json.dumps(probe))
    sample_dir = tmpdir.mkdir("sampled_video_frames")

    sample_video.sample_video(
        video_dir,
        Path(sample_dir),
        video_sample_distance=-1,
        video_sample_interval=2,
        rerun=True,
    )

    samples = sorted(Path(s) for s in sample_dir.join("hello.mp4").listdir())
    assert len(samples), "expect samples but got none"
    for idx, sample in enumerate(samples):
        assert sample.name == f"hello_2_{idx + 1:06d}.jpg"
        assert exif_read.ExifRead(
            sample
        ).extract_capture_time() == PROBE_START_TIME + datetime.timedelta(
            seconds=2 * idx
        )


def test_sample_video_from_gps_clock(tmpdir: py.path.local, setup_mock, monkeypatch):
    """A video's own GPS clock wins over the container's creation time."""
    root = _PWD.joinpath("data/mock_sample_video")
    video_dir = root.joinpath("videos")
    sample_dir = tmpdir.mkdir("sampled_video_frames")

    # A camera that stamps the creation time at the end of the recording, or in
    # local time, still has a correct absolute clock in its telemetry
    gps_start_time = datetime.datetime(
        2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
    )
    points = [
        telemetry.GPSPoint(
            time=float(i),
            lat=40.0 + i * 0.001,
            lon=-74.0,
            alt=None,
            angle=None,
            epoch_time=gps_start_time.timestamp() + i,
            fix=None,
            precision=None,
            ground_speed=None,
        )
        for i in range(3)
    ]
    monkeypatch.setattr(
        sample_video,
        "NativeVideoExtractor",
        lambda video_path: mock.Mock(
            extract=lambda: VideoMetadata(
                filename=video_path,
                filetype=FileType.BLACKVUE,
                points=T.cast(T.List[geo.Point], points),
            )
        ),
    )

    sample_video.sample_video(
        video_dir,
        Path(sample_dir),
        video_sample_distance=-1,
        video_sample_interval=2,
        rerun=True,
    )

    samples = sample_dir.join("hello.mp4").listdir()
    _validate_interval([Path(s) for s in samples], gps_start_time)


def test_sample_video_when_telemetry_fails(
    tmpdir: py.path.local, setup_mock, monkeypatch, caplog
):
    """A telemetry parser bug must not fail sampling, which did not need it."""
    root = _PWD.joinpath("data/mock_sample_video")
    video_dir = root.joinpath("videos")
    sample_dir = tmpdir.mkdir("sampled_video_frames")

    def raise_type_error():
        raise TypeError("'NoneType' object is not subscriptable")

    monkeypatch.setattr(
        sample_video,
        "NativeVideoExtractor",
        lambda video_path: mock.Mock(extract=raise_type_error),
    )

    with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
        sample_video.sample_video(
            video_dir,
            Path(sample_dir),
            video_sample_distance=-1,
            video_sample_interval=2,
            rerun=True,
        )

    samples = sample_dir.join("hello.mp4").listdir()
    _validate_interval([Path(s) for s in samples], PROBE_START_TIME)
    assert "Unable to read the telemetry of hello.mp4" in caplog.text


class TestSampleTimelapseByInterval:
    """
    Interval samples of a timelapse are stamped with their capture times, which
    its GPS clock spaces 10 times as far apart as the frames
    """

    GPS_START_TIME = datetime.datetime(
        2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
    )

    @classmethod
    def _mock_telemetry(cls, monkeypatch, gps_seconds: T.Callable[[int], float]):
        # One point per second of video, at gps_seconds(i) from GPS_START_TIME,
        # over more than a minute, which a pace off 1x takes to measure
        points = [
            telemetry.GPSPoint(
                time=float(i),
                lat=40.0 + i * 0.001,
                lon=-74.0,
                alt=None,
                angle=None,
                epoch_time=cls.GPS_START_TIME.timestamp() + gps_seconds(i),
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for i in range(70)
        ]
        monkeypatch.setattr(
            sample_video,
            "NativeVideoExtractor",
            lambda video_path: mock.Mock(
                extract=lambda: VideoMetadata(
                    filename=video_path,
                    filetype=FileType.GOPRO,
                    points=T.cast(T.List[geo.Point], points),
                )
            ),
        )

    @pytest.fixture
    def timelapse_telemetry(self, monkeypatch):
        # Recorded 10 seconds apart
        self._mock_telemetry(monkeypatch, lambda i: 10 * i)

    def _sample(self, tmpdir: py.path.local, **kwargs) -> list[Path]:
        root = _PWD.joinpath("data/mock_sample_video")
        sample_dir = tmpdir.mkdir("sampled_video_frames")
        sample_video.sample_video(
            root.joinpath("videos"),
            Path(sample_dir),
            video_sample_distance=-1,
            video_sample_interval=2,
            rerun=True,
            **kwargs,
        )
        return [Path(s) for s in sample_dir.join("hello.mp4").listdir()]

    def test_capture_times_follow_the_gps_clock(
        self, tmpdir, setup_mock, timelapse_telemetry, caplog
    ):
        _validate_interval(
            self._sample(tmpdir), self.GPS_START_TIME, seconds_per_sample=20
        )
        assert "--video_duration_ratio" not in caplog.text

    def _capture_times(self, samples: T.Sequence[Path]) -> list[float]:
        """In seconds from GPS_START_TIME"""
        return [
            round(
                (
                    exif_read.ExifRead(sample).extract_capture_time()
                    - self.GPS_START_TIME
                ).total_seconds(),
                3,
            )
            for sample in sorted(samples)
        ]

    def test_capture_times_follow_the_gps_clock_without_a_stale_timestamp(
        self, tmpdir, setup_mock, monkeypatch
    ):
        """
        The first GPS timestamp of a GoPro MAX timelapse can be seconds early,
        and starts neither the clock nor the samples
        """
        self._mock_telemetry(monkeypatch, lambda i: -10 if i == 0 else 10 * i)

        capture_times = self._capture_times(self._sample(tmpdir))

        assert len(capture_times) > 2
        assert capture_times == [20.0 * idx for idx in range(len(capture_times))]

    def test_a_normal_video_follows_its_gps_clock(
        self, tmpdir, setup_mock, monkeypatch
    ):
        """
        A second per second from the median of its timestamps, not through
        them: the first can be stale, and the others jitter
        """
        # The first timestamp 5 seconds stale, and the others half a second off
        # the line through them
        jitter = [0.0, 0.5, -0.5, 0.0]
        self._mock_telemetry(monkeypatch, lambda i: -5 if i == 0 else i + jitter[i % 4])

        capture_times = self._capture_times(self._sample(tmpdir))

        assert len(capture_times) > 2
        assert capture_times == [2.0 * idx for idx in range(len(capture_times))]

    def test_a_clock_that_gains_on_the_video(self, tmpdir, setup_mock, monkeypatch):
        """A LabPano's runs 8/7 times as fast as the video"""
        self._mock_telemetry(monkeypatch, lambda i: i * 8 / 7)

        capture_times = self._capture_times(self._sample(tmpdir))

        assert len(capture_times) > 2
        assert capture_times == pytest.approx(
            [2 * idx * 8 / 7 for idx in range(len(capture_times))], abs=0.001
        )

    def test_from_the_given_start_time(self, tmpdir, setup_mock, timelapse_telemetry):
        video_start_time = "2020_08_10_14_37_05_023"
        _validate_interval(
            self._sample(tmpdir, video_start_time=video_start_time),
            description.parse_capture_time(video_start_time),
            seconds_per_sample=20,
        )

    def test_the_gps_clock_wins_over_the_duration_ratio(
        self, tmpdir, setup_mock, timelapse_telemetry, caplog
    ):
        """
        The ratio is for the videos without a GPS clock, which a batch of
        videos may mix with videos that have one
        """
        _validate_interval(
            self._sample(tmpdir, video_duration_ratio=5),
            self.GPS_START_TIME,
            seconds_per_sample=20,
        )
        assert (
            "Ignoring --video_duration_ratio 5 for hello.mp4, whose own GPS clock runs at 10x"
            in caplog.text
        )

    def test_the_duration_ratio_paces_a_video_without_a_gps_clock(
        self, tmpdir, setup_mock
    ):
        _validate_interval(
            self._sample(tmpdir, video_duration_ratio=5),
            PROBE_START_TIME,
            seconds_per_sample=10,
        )


class TestLocateIntervalSamples:
    """
    Interval samples are located along the video's own GPS track, as distance
    samples are, so that the geotagging stage finds their positions in them
    """

    GPS_START_TIME = datetime.datetime(
        2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
    )

    # The position of the image that MOCK_FFMPEG copies for each sample
    MOCK_SAMPLE_LON_LAT = (14.498805555555554, 35.91251666666667)

    @classmethod
    def _points(cls, seconds: int) -> list[geo.Point]:
        # One point per second of video, recorded in real time
        return [
            telemetry.GPSPoint(
                time=float(i),
                lat=40.0 + i * 0.001,
                lon=-74.0,
                alt=100.0 + i,
                angle=None,
                epoch_time=cls.GPS_START_TIME.timestamp() + i,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for i in range(seconds)
        ]

    @staticmethod
    def _video_metadata(video_path: Path, points: T.Sequence[geo.Point]):
        return VideoMetadata(
            filename=video_path,
            filetype=FileType.GOPRO,
            points=list(points),
            make="GoPro",
            model="HERO7 Black",
        )

    def _sample(
        self, tmpdir, monkeypatch, track_points, read_by: int = 0, **kwargs
    ) -> list[Path]:
        """
        Sample the video every 2 seconds, its track read by the source at
        index **read_by** of those sampling tries
        """
        clock_points = self._points(60)
        monkeypatch.setattr(
            sample_video,
            "NativeVideoExtractor",
            lambda video_path: mock.Mock(
                extract=lambda: self._video_metadata(video_path, clock_points)
            ),
        )
        self.track_calls: list[list[SourceOption]] = []

        def fake_process(paths, options, sources=None):
            self.track_calls.append(list(options))
            [video_path] = paths
            if isinstance(track_points, Exception):
                return [
                    describe_error_metadata(
                        track_points, video_path, filetype=FileType.VIDEO
                    )
                ]
            if sources is not None:
                sources[video_path] = options[read_by]
            return [self._video_metadata(video_path, track_points)]

        monkeypatch.setattr(sample_video.factory, "process", fake_process)

        root = _PWD.joinpath("data/mock_sample_video")
        sample_dir = tmpdir.mkdir("sampled_video_frames")
        sample_video.sample_video(
            root.joinpath("videos"),
            Path(sample_dir),
            video_sample_distance=-1,
            video_sample_interval=2,
            rerun=True,
            **kwargs,
        )
        return sorted(Path(s) for s in sample_dir.join("hello.mp4").listdir())

    def test_located_along_the_video_track(self, tmpdir, setup_mock, monkeypatch):
        samples = self._sample(tmpdir, monkeypatch, self._points(60))

        _validate_interval(samples, self.GPS_START_TIME)
        for idx, sample in enumerate(samples):
            exif = exif_read.ExifRead(sample)
            # At the video time of the sample, 2 seconds apart
            lon_lat = exif.extract_lon_lat()
            assert lon_lat is not None
            assert lon_lat == pytest.approx((-74.0, 40.0 + 2 * idx * 0.001))
            assert exif.extract_altitude() == pytest.approx(100.0 + 2 * idx)
            # The bearing of the track, northwards
            assert exif.extract_direction() == pytest.approx(0.0)
            assert exif.extract_make() == "GoPro"
            assert exif.extract_model() == "HERO7 Black"
        # By the sources distance sampling reads, in this process
        [options] = self.track_calls
        assert [(o.source, o.num_processes) for o in options] == [
            (SourceType.NATIVE, 0)
        ]

    def test_samples_past_the_track_are_left_out(
        self, tmpdir, setup_mock, monkeypatch, caplog
    ):
        # The track ends 20 seconds into the video
        with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
            samples = self._sample(tmpdir, monkeypatch, self._points(21))

        assert [s.name for s in samples] == [
            f"hello_v_{idx + 1:06d}.jpg" for idx in range(11)
        ]
        lon_lats = [exif_read.ExifRead(s).extract_lon_lat() for s in samples]
        assert lon_lats[10] == pytest.approx((-74.0, 40.020))
        assert (
            "19 of the 30 samples of hello.mp4 fall outside its GPS track "
            "(2021-08-10T06:38:06+00:00 to 2021-08-10T06:38:26+00:00) and were left out"
            in caplog.text
        )

    @pytest.mark.parametrize(
        "geotag_source, left_out",
        [
            # video_process with the default sources, which read the positions
            # written into the samples
            ([], True),
            (["exif"], True),
            # The sample_video command, whose samples may be geotagged later
            # by the time since the first sample
            (None, False),
            (["gopro"], False),
            (['{"source": "exiftool_xml", "pattern": "%g.xml"}'], False),
        ],
    )
    def test_samples_before_the_track(
        self, tmpdir, setup_mock, monkeypatch, geotag_source, left_out
    ):
        # The track starts 5 seconds into the video
        track = self._points(60)[5:]
        kwargs = {} if geotag_source is None else {"geotag_source": geotag_source}

        samples = self._sample(tmpdir, monkeypatch, track, **kwargs)

        names = [s.name for s in samples]
        if left_out:
            assert names[0] == "hello_v_000004.jpg"
            assert len(samples) == 27
        else:
            # Left in, without a position, so that the others keep theirs
            assert names[0] == "hello_v_000001.jpg"
            assert len(samples) == 30
            lon_lats = [exif_read.ExifRead(s).extract_lon_lat() for s in samples]
            assert all(lon_lat == self.MOCK_SAMPLE_LON_LAT for lon_lat in lon_lats[:3])
            assert lon_lats[3] == pytest.approx((-74.0, 40.006))

    def test_none_left_out_if_the_track_covers_none(
        self, tmpdir, setup_mock, monkeypatch, caplog
    ):
        """So that a video that misses its track does not go without a word"""
        track = [dataclasses.replace(p, time=p.time + 100.0) for p in self._points(10)]
        with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
            samples = self._sample(tmpdir, monkeypatch, track, geotag_source=[])

        assert len(samples) == 30
        assert "left out" not in caplog.text

    def test_not_located_without_a_track(self, tmpdir, setup_mock, monkeypatch, caplog):
        with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
            samples = self._sample(
                tmpdir,
                monkeypatch,
                exceptions.MapillaryVideoGPSNotFoundError("No GPS data found"),
            )

        _validate_interval(samples, self.GPS_START_TIME)
        assert all(
            exif_read.ExifRead(s).extract_lon_lat() == self.MOCK_SAMPLE_LON_LAT
            for s in samples
        )
        assert (
            "The samples of hello.mp4 are not geotagged, as no GPS track was read from it: No GPS data found"
            in caplog.text
        )

    def _file_points(self, video_times, gps_offset: float = 100.0) -> list[geo.Point]:
        """
        The points of a track from a file as GPX sync places them on the
        video, at video times, keeping their own GPS times
        """
        return [
            telemetry.CAMMGPSPoint(
                time=float(t),
                lat=40.0 + t * 0.001,
                lon=-74.0,
                alt=None,
                angle=None,
                epoch_time=self.GPS_START_TIME.timestamp() + gps_offset + t,
                gps_fix_type=2,
                horizontal_accuracy=0.0,
                vertical_accuracy=0.0,
                velocity_east=0.0,
                velocity_north=0.0,
                velocity_up=0.0,
                speed_accuracy=0.0,
            )
            for t in video_times
        ]

    @pytest.mark.parametrize("source", ["gpx", "nmea"])
    def test_located_along_a_video_track_file(
        self, tmpdir, setup_mock, monkeypatch, caplog, source
    ):
        """
        Along the track of --video_geotag_source as GPX sync placed it on the
        video, and stamped with its times, as distance samples are. It ends 40
        seconds into the video
        """
        track = self._file_points(range(41))
        with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
            samples = self._sample(
                tmpdir,
                monkeypatch,
                track,
                video_geotag_source=[source],
                geotag_source_path=Path(tmpdir) / f"track.{source}",
            )

        assert len(samples) == 21
        _validate_interval(
            samples, self.GPS_START_TIME + datetime.timedelta(seconds=100)
        )
        for idx, sample in enumerate(samples):
            lon_lat = exif_read.ExifRead(sample).extract_lon_lat()
            assert lon_lat == pytest.approx((-74.0, 40.0 + 2 * idx * 0.001))
        [options] = self.track_calls
        assert [o.source.value for o in options] == [source]
        assert (
            "9 of the 30 samples of hello.mp4 fall outside its GPS track "
            "(2021-08-10T06:39:46+00:00 to 2021-08-10T06:40:26+00:00) and were left out"
            in caplog.text
        )

    @pytest.mark.parametrize(
        "video_geotag_source",
        # Whatever source follows the one that read the track
        [["gpx"], ["gpx", "native"], ["nmea", "exiftool_runtime"]],
    )
    def test_samples_in_a_gap_of_a_video_track_file_are_left_out(
        self, tmpdir, setup_mock, monkeypatch, video_geotag_source
    ):
        monkeypatch.setattr(sample_video.constants, "MAX_GPX_GAP_SECONDS", 5.0)
        track = self._file_points([*range(11), *range(20, 61)])

        samples = self._sample(
            tmpdir,
            monkeypatch,
            track,
            video_geotag_source=video_geotag_source,
            geotag_source_path=Path(tmpdir) / "track.gpx",
        )

        # Not those at 12, 14, 16 and 18 seconds
        assert [s.name for s in samples] == [
            f"hello_v_{idx + 1:06d}.jpg" for idx in [*range(6), *range(10, 30)]
        ]

    @pytest.mark.parametrize("video_geotag_source", [["gpx"], ["gpx", "native"]])
    def test_a_video_track_file_started_with_the_video_starts_at_the_first_sample(
        self, tmpdir, setup_mock, monkeypatch, video_geotag_source
    ):
        """
        GPX sync starts it at the first frame, 0.5 seconds into the video, and
        ffmpeg cuts the first interval sample at time 0
        """
        monkeypatch.setattr(gpx_extractor, "_first_frame_time", lambda path: 0.5)
        track = self._file_points([0.5 + t for t in range(61)], gps_offset=-0.5)

        samples = self._sample(
            tmpdir,
            monkeypatch,
            track,
            video_geotag_source=video_geotag_source,
            geotag_source_path=Path(tmpdir) / "track.gpx",
            interpolation_use_gpx_start_time=True,
        )

        assert len(samples) == 30
        _validate_interval(samples, self.GPS_START_TIME)
        lon_lat = exif_read.ExifRead(samples[0]).extract_lon_lat()
        assert lon_lat == pytest.approx((-74.0, 40.0005))

    @pytest.mark.parametrize(
        "video_geotag_source",
        # After a GPX that misses the video, or before a GPX
        [["gpx", "native"], ["native", "gpx"]],
    )
    def test_a_track_read_by_the_video_is_located_along_as_its_own(
        self, tmpdir, setup_mock, monkeypatch, video_geotag_source
    ):
        """
        The video's own track, with a gap over the limit from 10 to 20 seconds,
        locates the samples as without a GPX
        """
        monkeypatch.setattr(sample_video.constants, "MAX_GPX_GAP_SECONDS", 5.0)
        track = [p for p in self._points(60) if not 10 < p.time < 20]

        samples = self._sample(
            tmpdir.mkdir("both"),
            monkeypatch,
            track,
            read_by=video_geotag_source.index("native"),
            video_geotag_source=video_geotag_source,
            geotag_source_path=Path(tmpdir) / "track.gpx",
        )
        own = self._sample(
            tmpdir.mkdir("own"), monkeypatch, track, video_geotag_source=["native"]
        )

        assert len(samples) == 30
        assert [s.name for s in samples] == [s.name for s in own]
        for sample, own_sample in zip(samples, own):
            exif, own_exif = exif_read.ExifRead(sample), exif_read.ExifRead(own_sample)
            assert exif.extract_capture_time() == own_exif.extract_capture_time()
            assert exif.extract_lon_lat() == own_exif.extract_lon_lat()

    def test_none_left_out_of_a_video_track_file_where_the_video_source_may_geotag_them(
        self, tmpdir, setup_mock, monkeypatch
    ):
        """The legacy gopro source geotags the samples by the GPS of the video"""
        track = self._file_points(range(41))

        samples = self._sample(
            tmpdir,
            monkeypatch,
            track,
            video_geotag_source=["gpx"],
            geotag_source=["gopro"],
            geotag_source_path=Path(tmpdir) / "track.gpx",
        )

        assert len(samples) == 30

    @pytest.mark.parametrize("source", [SourceType.GPX, SourceType.NMEA])
    def test_not_located_with_a_track_file(self, monkeypatch, source):
        """
        The geotagging stage places the samples along a GPX or NMEA track of
        --geotag_source by their capture times, which interval sampling does not
        place the track by
        """
        process = mock.Mock()
        monkeypatch.setattr(sample_video.factory, "process", process)

        track = sample_video._read_track_for_interval_samples(
            Path("video.mp4"),
            [SourceOption(source), SourceOption(SourceType.NATIVE)],
        )

        assert track is None
        process.assert_not_called()


class TestSampleNoisyTimelapseByInterval:
    """
    GPS rejected as noise gives interval sampling no telemetry to read a clock
    from, but GPX sync reads one from it. The samples are stamped by that
    clock, so that the geotagging stage places them along the GPX where GPX
    sync does
    """

    GPS_START_TIME = TestSampleTimelapseByInterval.GPS_START_TIME

    @classmethod
    def _mock_noisy_telemetry(cls, monkeypatch, gps_start_time: float):
        # One point per second of video, recorded 10 seconds apart
        points = [
            telemetry.GPSPoint(
                time=float(i),
                lat=40.0,
                lon=-74.0,
                alt=None,
                angle=None,
                epoch_time=gps_start_time + 10 * i,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for i in range(60)
        ]

        def reject_as_noise():
            raise exceptions.MapillaryGPSNoiseError("GPS too noisy")

        monkeypatch.setattr(
            sample_video,
            "NativeVideoExtractor",
            lambda video_path: mock.Mock(extract=reject_as_noise),
        )
        monkeypatch.setattr(
            sample_video.GPXVideoExtractor,
            "_extract_native_video_metadata",
            lambda self: (
                VideoMetadata(
                    filename=self.video_path,
                    filetype=FileType.GOPRO,
                    points=T.cast(T.List[geo.Point], points),
                ),
                True,
            ),
        )

    def _write_gpx(
        self, path: Path, start: datetime.datetime, num_points: int = 62
    ) -> Path:
        # By default over the 610 seconds that the 61 seconds of video span
        trkpts = "".join(
            f'<trkpt lat="{40.0 + i * 1e-4:.7f}" lon="-74.0"><time>'
            f"{(start + datetime.timedelta(seconds=10 * i)).strftime('%Y-%m-%dT%H:%M:%SZ')}"
            "</time></trkpt>"
            for i in range(num_points)
        )
        path.write_text(
            '<?xml version="1.0"?><gpx version="1.1" creator="test" '
            'xmlns="http://www.topografix.com/GPX/1/1">'
            f"<trk><trkseg>{trkpts}</trkseg></trk></gpx>"
        )
        return path

    def _sample(self, tmpdir: py.path.local, **kwargs) -> list[Path]:
        root = _PWD.joinpath("data/mock_sample_video")
        sample_dir = tmpdir.mkdir("sampled_video_frames")
        sample_video.sample_video(
            root.joinpath("videos"),
            Path(sample_dir),
            video_sample_distance=-1,
            video_sample_interval=2,
            rerun=True,
            **kwargs,
        )
        return [Path(s) for s in sample_dir.join("hello.mp4").listdir()]

    def test_stamped_by_the_clock_that_syncs_the_gpx(
        self, tmpdir, setup_mock, monkeypatch
    ):
        self._mock_noisy_telemetry(monkeypatch, self.GPS_START_TIME.timestamp())
        gpx = self._write_gpx(Path(tmpdir) / "track.gpx", self.GPS_START_TIME)

        _validate_interval(
            self._sample(tmpdir, geotag_source=["gpx"], geotag_source_path=gpx),
            self.GPS_START_TIME,
            seconds_per_sample=20,
        )

    def test_started_with_the_gpx_at_the_pace_of_the_clock(
        self, tmpdir, setup_mock, monkeypatch
    ):
        """
        With --interpolation_use_gpx_start_time, the clock gives only the pace:
        the samples were all stamped within the first minute of the track
        """
        # A clock a year away from the GPX, whose start replaces it. A clock
        # that never got past a placeholder date before 2016 gives no pace
        self._mock_noisy_telemetry(
            monkeypatch,
            datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc).timestamp(),
        )
        gpx_start = self.GPS_START_TIME + datetime.timedelta(minutes=5)
        gpx = self._write_gpx(Path(tmpdir) / "track.gpx", gpx_start)

        _validate_interval(
            self._sample(
                tmpdir,
                geotag_source=["gpx"],
                geotag_source_path=gpx,
                interpolation_use_gpx_start_time=True,
            ),
            gpx_start,
            seconds_per_sample=20,
        )

    def test_started_with_the_gpx_at_time_0(self, tmpdir, setup_mock, monkeypatch):
        """
        ffmpeg cuts the first interval sample at time 0, whatever the
        composition time of the first frame, at which distance sampling starts
        the track
        """
        monkeypatch.setattr(gpx_extractor, "_first_frame_time", lambda path: 0.5)
        self._mock_noisy_telemetry(monkeypatch, self.GPS_START_TIME.timestamp())
        gpx = self._write_gpx(Path(tmpdir) / "track.gpx", self.GPS_START_TIME)

        _validate_interval(
            self._sample(
                tmpdir,
                geotag_source=["gpx"],
                geotag_source_path=gpx,
                interpolation_use_gpx_start_time=True,
            ),
            self.GPS_START_TIME,
            seconds_per_sample=20,
        )

    def test_samples_outside_the_gpx_are_left_out(
        self, tmpdir, setup_mock, monkeypatch, caplog
    ):
        """
        The geotagging stage locates them along the GPX by their capture
        times, and would fail the 5 samples before it starts
        """
        self._mock_noisy_telemetry(monkeypatch, self.GPS_START_TIME.timestamp())
        gpx_start = self.GPS_START_TIME + datetime.timedelta(seconds=100)
        gpx = self._write_gpx(Path(tmpdir) / "track.gpx", gpx_start)

        with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
            samples = self._sample(
                tmpdir, geotag_source=["gpx"], geotag_source_path=gpx
            )

        assert sorted(s.name for s in samples) == [
            f"hello_v_{idx + 1:06d}.jpg" for idx in range(5, 30)
        ]
        assert (
            "5 of the 30 samples of hello.mp4 fall outside its GPS track "
            "(2021-08-10T06:39:46+00:00 to 2021-08-10T06:49:56+00:00) and were left out"
            in caplog.text
        )

    def test_samples_past_the_gpx_started_with_the_video_are_left_out(
        self, tmpdir, setup_mock, monkeypatch
    ):
        self._mock_noisy_telemetry(monkeypatch, self.GPS_START_TIME.timestamp())
        # 200 seconds long: the samples 20 seconds apart until then
        gpx = self._write_gpx(Path(tmpdir) / "track.gpx", self.GPS_START_TIME, 21)

        samples = self._sample(
            tmpdir,
            geotag_source=["gpx"],
            geotag_source_path=gpx,
            interpolation_use_gpx_start_time=True,
        )

        _validate_interval(samples, self.GPS_START_TIME, seconds_per_sample=20)
        assert len(samples) == 11

    def test_none_left_out_where_the_video_source_may_geotag_them(
        self, tmpdir, setup_mock, monkeypatch
    ):
        """The legacy gopro source geotags the samples by the GPS of the video"""
        self._mock_noisy_telemetry(monkeypatch, self.GPS_START_TIME.timestamp())
        gpx_start = self.GPS_START_TIME + datetime.timedelta(seconds=100)
        gpx = self._write_gpx(Path(tmpdir) / "track.gpx", gpx_start)

        samples = self._sample(
            tmpdir, geotag_source=["gpx", "gopro"], geotag_source_path=gpx
        )

        assert len(samples) == 30

    def test_none_left_out_of_several_videos_started_with_the_gpx(
        self, tmp_path, setup_mock, monkeypatch
    ):
        """
        The geotagging stage starts the GPX at the first sample of them all,
        which the sampling of one video does not know
        """
        self._mock_noisy_telemetry(monkeypatch, self.GPS_START_TIME.timestamp())
        gpx = self._write_gpx(tmp_path / "track.gpx", self.GPS_START_TIME, 21)
        interpolation = InterpolationOption(use_gpx_start_time=True)
        geotag_options = sample_video._parse_geotag_options(
            ["gpx"], gpx, None, tmp_path, VideoSyncOption(), interpolation
        )
        sample_sources = sample_video._parse_sample_sources(
            ["gpx"], gpx, tmp_path, interpolation
        )
        video = _PWD.joinpath("data/mock_sample_video/videos/hello.mp4")

        for single_video, num_samples in [(True, 11), (False, 30)]:
            sample_dir = tmp_path / f"samples_{single_video}"
            sample_video._sample_single_video_by_interval(
                video,
                sample_dir,
                sample_interval=2,
                duration_ratio=1.0,
                geotag_options=geotag_options,
                sample_sources=sample_sources,
                single_video=single_video,
            )
            assert len(list(sample_dir.iterdir())) == num_samples

    def test_not_by_a_placeholder_clock(self, tmpdir, setup_mock, monkeypatch):
        """
        Which GPX sync does not place the GPX by either, nor by the creation
        time of the video: the track is assumed to start with the video
        """
        self._mock_noisy_telemetry(
            monkeypatch,
            datetime.datetime(2015, 1, 1, tzinfo=datetime.timezone.utc).timestamp(),
        )
        gpx = self._write_gpx(Path(tmpdir) / "track.gpx", self.GPS_START_TIME)

        _validate_interval(
            self._sample(tmpdir, geotag_source=["gpx"], geotag_source_path=gpx),
            self.GPS_START_TIME,
        )

    def test_not_by_the_creation_time_within_the_gpx(
        self, tmpdir, setup_mock, monkeypatch
    ):
        """
        The creation time of the video, which the camera's clock stamps, places
        nothing, even where the track covers it
        """
        self._mock_noisy_telemetry(
            monkeypatch,
            datetime.datetime(2015, 1, 1, tzinfo=datetime.timezone.utc).timestamp(),
        )
        gpx_start = PROBE_START_TIME - datetime.timedelta(seconds=100)
        gpx = self._write_gpx(Path(tmpdir) / "track.gpx", gpx_start)

        _validate_interval(
            self._sample(tmpdir, geotag_source=["gpx"], geotag_source_path=gpx),
            gpx_start,
        )

    def test_not_without_a_gpx(self, tmpdir, setup_mock, monkeypatch):
        """The video's own GPS geotags the samples, and rejects them"""
        self._mock_noisy_telemetry(monkeypatch, self.GPS_START_TIME.timestamp())

        _validate_interval(self._sample(tmpdir), PROBE_START_TIME)


class TestGPXStartTimeByInterval:
    """
    With --interpolation_use_gpx_start_time, the geotagging stage puts the
    first frame of a video without a GPS clock at the start of the GPX, and
    the others at --video_duration_ratio. A track that runs on long after the
    video is refused, as in distance sampling.
    """

    # 5.76 seconds long, without GPS
    VIDEO = _PWD.parent.joinpath("data", "videos", "sample-5s.mp4")

    @staticmethod
    def _write_gpx(path: Path, seconds: int) -> Path:
        start = datetime.datetime(2025, 3, 14, 7, 0, 0, tzinfo=datetime.timezone.utc)
        trkpts = "".join(
            f'<trkpt lat="{37.0 + i * 1e-4:.7f}" lon="-122.0"><time>'
            f"{(start + datetime.timedelta(seconds=i)).strftime('%Y-%m-%dT%H:%M:%SZ')}"
            "</time></trkpt>"
            for i in range(seconds + 1)
        )
        path.write_text(
            '<?xml version="1.0"?><gpx version="1.1" creator="test" '
            'xmlns="http://www.topografix.com/GPX/1/1">'
            f"<trk><trkseg>{trkpts}</trkseg></trk></gpx>"
        )
        return path

    def test_a_track_far_longer_than_the_video_is_refused(
        self, tmp_path, setup_mock, caplog
    ):
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        shutil.copyfile(self.VIDEO, video_dir / self.VIDEO.name)
        gpx = self._write_gpx(tmp_path / "track.gpx", seconds=60)

        with pytest.raises(exceptions.MapillaryVideoSampleError):
            sample_video.sample_video(
                video_dir,
                tmp_path / "samples",
                video_sample_distance=-1,
                video_sample_interval=2,
                geotag_source=["gpx"],
                geotag_source_path=gpx,
                interpolation_use_gpx_start_time=True,
            )

        assert "--video_duration_ratio" in caplog.text

    def test_a_track_that_ends_with_the_video_at_the_ratio_passes(self, tmp_path):
        """The video spans 57.6s of GPS time at 10 seconds per second."""
        gpx = self._write_gpx(tmp_path / "track.gpx", seconds=57)
        video_sync = VideoSyncOption(duration_ratio=10)
        options = sample_video._parse_geotag_options(
            ["gpx"],
            gpx,
            None,
            tmp_path,
            video_sync,
            InterpolationOption(use_gpx_start_time=True),
        )

        sample_video._check_gpx_start_by_interval(self.VIDEO, options, video_sync)

    def test_an_nmea_track_is_checked_as_a_gpx_track(self, tmp_path):
        start = datetime.datetime(2025, 3, 14, 7, 0, 0, tzinfo=datetime.timezone.utc)
        nmea = tmp_path / "track.nmea"
        lines = []
        for i in range(61):
            hhmmss = (start + datetime.timedelta(seconds=i)).strftime("%H%M%S.00")
            position = (f"3700.{i:04d}", "N", "12200.0000", "W")
            rmc = (hhmmss, "A", *position, "0.0", "0.0", "140325", "", "", "A")
            gga = (hhmmss, *position, "1", "08", "1.0", "0.0", "M", "0.0", "M", "", "")
            lines.append(str(pynmea2.RMC("GP", "RMC", rmc)))
            lines.append(str(pynmea2.GGA("GP", "GGA", gga)))
        nmea.write_text("".join(f"{line}\r\n" for line in lines))
        video_sync = VideoSyncOption()
        options = sample_video._parse_geotag_options(
            ["nmea"],
            nmea,
            None,
            tmp_path,
            video_sync,
            InterpolationOption(use_gpx_start_time=True),
        )

        with pytest.raises(exceptions.MapillaryGPXVideoStartUnknownError) as excinfo:
            sample_video._check_gpx_start_by_interval(self.VIDEO, options, video_sync)

        assert str(excinfo.value).startswith(f"The NMEA track in {nmea} lasts")

    def test_gps_rejected_as_noise_still_has_a_clock(self, tmp_path, monkeypatch):
        """
        Interval sampling reads no telemetry from GPS rejected as noise, but
        GPX sync reads its clock, and syncs the GPX at that clock's pace, as
        for any video with a GPS clock
        """
        # A 12x timelapse clock
        points = [
            telemetry.GPSPoint(
                time=i * 0.1,
                lat=37.0,
                lon=-122.0,
                alt=None,
                angle=None,
                epoch_time=1741935600.0 + i * 1.2,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for i in range(30)
        ]
        monkeypatch.setattr(
            sample_video.GPXVideoExtractor,
            "_extract_native_video_metadata",
            lambda _self: (
                VideoMetadata(
                    filename=self.VIDEO,
                    filetype=FileType.GOPRO,
                    points=T.cast(T.List[geo.Point], points),
                ),
                True,
            ),
        )
        gpx = self._write_gpx(tmp_path / "track.gpx", seconds=60)
        video_sync = VideoSyncOption()
        options = sample_video._parse_geotag_options(
            ["gpx"],
            gpx,
            None,
            tmp_path,
            video_sync,
            InterpolationOption(use_gpx_start_time=True),
        )

        sample_video._check_gpx_start_by_interval(self.VIDEO, options, video_sync)


class TestGPSClockStartTime:
    """Tests for _gps_clock_start_time."""

    @staticmethod
    def _gps_point(time: float, epoch_time: float | None) -> telemetry.GPSPoint:
        return telemetry.GPSPoint(
            time=time,
            lat=40.0,
            lon=-74.0,
            alt=None,
            angle=None,
            epoch_time=epoch_time,
            fix=None,
            precision=None,
            ground_speed=None,
        )

    def test_maps_first_timestamp_back_to_video_start(self) -> None:
        # The first point is 2.5s into the video, so the video started 2.5s
        # before that point was recorded
        points = [self._gps_point(2.5, 1628599086.0)]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 3, 500000, tzinfo=datetime.timezone.utc
        )

    def test_skips_points_without_a_timestamp(self) -> None:
        points = [self._gps_point(0.0, None), self._gps_point(1.0, 1628599086.0)]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 5, tzinfo=datetime.timezone.utc
        )

    def test_skips_unset_clock(self) -> None:
        # GoPro reports 2000-01-01 until it gets its first fix
        points = [
            self._gps_point(0.0, 946684800.0),
            self._gps_point(1.0, 1628599086.0),
        ]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 5, tzinfo=datetime.timezone.utc
        )

    def test_skips_future_timestamps(self) -> None:
        points = [
            self._gps_point(0.0, time.time() + 7 * 24 * 3600),
            self._gps_point(1.0, 1628599086.0),
        ]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 5, tzinfo=datetime.timezone.utc
        )

    def test_skips_non_finite_timestamps(self) -> None:
        points = [
            self._gps_point(float("nan"), 1628599086.0),
            self._gps_point(0.0, float("inf")),
            self._gps_point(0.0, 1e300),
            self._gps_point(1.0, 1628599086.0),
        ]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 5, tzinfo=datetime.timezone.utc
        )

    def test_only_implausible_timestamps(self) -> None:
        points = [self._gps_point(0.0, 946684800.0), self._gps_point(1.0, 1e300)]
        assert sample_video._gps_clock_start_time(points) is None

    def test_median_ignores_a_bad_timestamp(self) -> None:
        epoch_times = [1628599086.0 + i for i in range(5)]
        epoch_times[0] += 30
        points = [self._gps_point(float(i), t) for i, t in enumerate(epoch_times)]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 6, tzinfo=datetime.timezone.utc
        )

    def test_uses_the_clock_rate_of_a_timelapse(self) -> None:
        # Each second of this timelapse spans 10 seconds of GPS time, so the
        # offset between the two clocks grows by 9 seconds per point: mapped
        # back at the rate of the clock, every point says the same start
        points = [self._gps_point(float(i), 1628599086.0 + 10 * i) for i in range(1000)]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 6, tzinfo=datetime.timezone.utc
        )

    def test_skips_a_placeholder_date(self) -> None:
        # GoPro stamps a date in October 2015 until it acquires the GPS time
        points = [
            self._gps_point(0.0, 1445507624.0),
            self._gps_point(1.0, 1445507625.0),
        ]
        assert sample_video._gps_clock_start_time(points) is None

    def test_no_absolute_timestamps(self) -> None:
        assert sample_video._gps_clock_start_time(_make_gps_points(3)) is None

    def test_no_points(self) -> None:
        assert sample_video._gps_clock_start_time([]) is None


class TestCreationTimeToStartTime:
    """Tests for _creation_time_to_start_time."""

    # A 60-second video, so the start is a minute before this if the camera
    # stamped the end
    CREATION_TIME = datetime.datetime(
        2023, 3, 7, 1, 36, 34, tzinfo=datetime.timezone.utc
    )
    START_TIME_IF_END_STAMPED = datetime.datetime(
        2023, 3, 7, 1, 35, 34, tzinfo=datetime.timezone.utc
    )

    @staticmethod
    def _probe(
        creation_time: str | None = "2023-03-07T01:36:34.000000Z",
        duration: str | None = "60.0",
        format_tags: dict[str, str] | None = None,
    ) -> ffmpeglib.Probe:
        stream: dict[str, T.Any] = {
            "index": 0,
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "tags": {},
        }
        if creation_time is not None:
            stream["tags"]["creation_time"] = creation_time
        if duration is not None:
            stream["duration"] = duration
        return ffmpeglib.Probe(
            T.cast(
                ffmpeglib.ProbeOutput,
                {"streams": [stream], "format": {"tags": format_tags or {}}},
            )
        )

    @staticmethod
    def _video(tmp_path: Path, name: str, data: bytes = b"") -> Path:
        video_path = tmp_path / name
        video_path.write_bytes(data)
        return video_path

    def test_assumes_start_without_evidence(self, tmp_path: Path, caplog) -> None:
        video_path = self._video(tmp_path, "clip.mp4")
        with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
            start_time = sample_video._creation_time_to_start_time(
                video_path, self._probe()
            )
        assert start_time == self.CREATION_TIME
        # Tells the user how to override it if the camera stamps the end
        assert "--video_start_time 2023_03_07_01_35_34_000" in caplog.text

    def test_known_end_stamping_camera(self, tmp_path: Path) -> None:
        video_path = self._video(tmp_path, "R0020627.MP4")
        probe = self._probe(format_tags={"make": "RICOH", "model": "RICOH THETA X"})
        assert (
            sample_video._creation_time_to_start_time(video_path, probe)
            == self.START_TIME_IF_END_STAMPED
        )

    def test_other_models_of_the_same_make(self, tmp_path: Path) -> None:
        video_path = self._video(tmp_path, "R0010001.MP4")
        probe = self._probe(format_tags={"make": "RICOH", "model": "RICOH THETA Z1"})
        assert (
            sample_video._creation_time_to_start_time(video_path, probe)
            == self.CREATION_TIME
        )

    def test_blackvue_without_gps_fix(self, tmp_path: Path) -> None:
        # BlackVue stamps the end. Without a fix there is no GPS clock to read
        # the start from, but its GPS box is still there to identify it
        box = {
            "type": b"free",
            "data": [
                {"type": b"gps ", "data": b"[1678152934000]$GPRMC,,V,,,,,,,,,,N*53"}
            ],
        }
        data = cparser.Box32ConstructBuilder({b"free": {}}).Box.build(box)
        video_path = self._video(tmp_path, "clip.mp4", data)
        assert (
            sample_video._creation_time_to_start_time(video_path, self._probe())
            == self.START_TIME_IF_END_STAMPED
        )

    def test_file_name_matches_end(self, tmp_path: Path) -> None:
        # Viofo names files by the start in local time (UTC+9 here), and stamps
        # the creation time at the end. The two clocks can be seconds apart
        for name in ["2023_0307_103534_0001F.MP4", "2023_0307_103544_0001F.MP4"]:
            video_path = self._video(tmp_path, name)
            assert (
                sample_video._creation_time_to_start_time(video_path, self._probe())
                == self.START_TIME_IF_END_STAMPED
            )

    def test_file_name_matches_end_with_naive_creation_time(
        self, tmp_path: Path
    ) -> None:
        video_path = self._video(tmp_path, "2023_0307_103534_0001F.MP4")
        probe = self._probe(creation_time="2023-03-07 01:36:34")
        assert sample_video._creation_time_to_start_time(
            video_path, probe
        ) == datetime.datetime(2023, 3, 7, 1, 35, 34)

    def test_file_name_matches_start(self, tmp_path: Path) -> None:
        # Insta360 names files a few seconds after it stamps the creation time
        for name in ["VID_20230307_103634_00_001.mp4", "VID_20230307_103644.mp4"]:
            video_path = self._video(tmp_path, name)
            assert (
                sample_video._creation_time_to_start_time(video_path, self._probe())
                == self.CREATION_TIME
            )

    def test_file_name_matches_both(self, tmp_path: Path, caplog) -> None:
        # A 15-minute video starts and ends at times that are both a whole
        # time zone away from the file name
        video_path = self._video(tmp_path, "20230307_103634.mp4")
        with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
            start_time = sample_video._creation_time_to_start_time(
                video_path, self._probe(duration="900.0")
            )
        assert start_time == self.CREATION_TIME
        assert "--video_start_time" in caplog.text

    def test_file_name_matches_neither(self, tmp_path: Path) -> None:
        for name in ["20230307_104004.mp4", "20230309_103634.mp4"]:
            video_path = self._video(tmp_path, name)
            assert (
                sample_video._creation_time_to_start_time(video_path, self._probe())
                == self.CREATION_TIME
            )

    def test_file_name_with_invalid_date(self, tmp_path: Path) -> None:
        video_path = self._video(tmp_path, "20231399_103534.mp4")
        assert (
            sample_video._creation_time_to_start_time(video_path, self._probe())
            == self.CREATION_TIME
        )

    def test_no_creation_time(self, tmp_path: Path) -> None:
        video_path = self._video(tmp_path, "clip.mp4")
        probe = self._probe(creation_time=None)
        assert sample_video._creation_time_to_start_time(video_path, probe) is None

    def test_no_duration(self, tmp_path: Path) -> None:
        video_path = self._video(tmp_path, "2023_0307_103534_0001F.MP4")
        probe = self._probe(duration=None)
        assert (
            sample_video._creation_time_to_start_time(video_path, probe)
            == self.CREATION_TIME
        )


# ---------------------------------------------------------------------------
# Helpers for distance-based sampling tests
# ---------------------------------------------------------------------------

MOCK_PROBE_JSON = _PWD / "data" / "mock_sample_video" / "videos" / "hello.mp4"
TEST_EXIF_JPG = _PWD / "data" / "test_exif.jpg"


def _load_probe_output() -> ffmpeglib.ProbeOutput:
    with open(MOCK_PROBE_JSON) as fp:
        return T.cast(ffmpeglib.ProbeOutput, json.load(fp))


def _make_gps_points(
    n: int = 10,
    start_lat: float = 40.0,
    start_lon: float = -74.0,
    lat_step: float = 0.001,
    lon_step: float = 0.001,
    time_step: float = 1.0,
) -> list[geo.Point]:
    """Create a synthetic GPS track with n points."""
    return [
        geo.Point(
            time=i * time_step,
            lat=start_lat + i * lat_step,
            lon=start_lon + i * lon_step,
            alt=10.0,
            angle=45.0,
        )
        for i in range(n)
    ]


def _make_sample(
    composition_time: float,
    timedelta: float = 0.033,
) -> mp4_sample_parser.Sample:
    """Create a synthetic mp4 Sample at the given composition time."""
    raw = mp4_sample_parser.RawSample(
        description_idx=1,
        offset=0,
        size=1000,
        timedelta=int(timedelta * 1000),
        composition_offset=0,
        is_sync=True,
    )
    return mp4_sample_parser.Sample(
        raw_sample=raw,
        exact_time=composition_time,
        exact_composition_time=composition_time,
        exact_timedelta=timedelta,
        description={},
    )


def _create_fake_frames(
    sample_dir: Path,
    video_stem: str,
    stream_specifier: str,
    num_frames: int,
) -> list[Path]:
    """Create fake JPEG frame files in sample_dir mimicking ffmpeg output."""
    os.makedirs(sample_dir, exist_ok=True)
    paths: list[Path] = []
    for i in range(1, num_frames + 1):
        name = f"{video_stem}_{stream_specifier}_{i:06d}.jpg"
        frame_path = sample_dir / name
        shutil.copy(str(TEST_EXIF_JPG), str(frame_path))
        paths.append(frame_path)
    return paths


# ---------------------------------------------------------------------------
# Distance-based sampling: _within_track_time_range_buffered
# ---------------------------------------------------------------------------


class TestWithinTrackTimeRangeBuffered:
    """Tests for _within_track_time_range_buffered."""

    def test_within_range(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, 2.0) is True

    def test_at_start_boundary(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, 0.0) is True

    def test_at_end_boundary(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, 4.0) is True

    def test_within_1ms_buffer_before_start(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, -0.0005) is True

    def test_within_1ms_buffer_after_end(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, 4.0005) is True

    def test_outside_buffer_before_start(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, -0.002) is False

    def test_outside_buffer_after_end(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, 4.002) is False

    def test_exactly_at_1ms_boundary(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, -0.001) is True
        assert sample_video._within_track_time_range_buffered(points, 4.001) is True


# ---------------------------------------------------------------------------
# Distance-based sampling: _sample_video_stream_by_distance
# ---------------------------------------------------------------------------


class TestSampleVideoStreamByDistance:
    """Tests for _sample_video_stream_by_distance."""

    def test_selects_frames_by_distance(self) -> None:
        """Frames spaced farther than sample_distance should be selected."""
        points = _make_gps_points(10, lat_step=0.001, time_step=1.0)
        samples = [_make_sample(float(i)) for i in range(10)]

        mock_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_parser.extract_samples.return_value = iter(samples)

        result = sample_video._sample_video_stream_by_distance(
            points, mock_parser, sample_distance=50.0
        )

        # Each point is ~111m apart in lat, so all 10 should be selected
        assert len(result) == 10
        assert all(idx in result for idx in range(10))

    def test_filters_close_frames(self) -> None:
        """Frames closer than sample_distance should be filtered out."""
        # ~15m apart (0.0001 degree in each axis)
        points = _make_gps_points(10, lat_step=0.0001, lon_step=0.0001, time_step=1.0)
        samples = [_make_sample(float(i)) for i in range(10)]

        mock_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_parser.extract_samples.return_value = iter(samples)

        result = sample_video._sample_video_stream_by_distance(
            points, mock_parser, sample_distance=50.0
        )

        assert len(result) < 10
        assert 0 in result  # first frame is always selected

    def test_zero_distance_selects_all(self) -> None:
        """With sample_distance=0, all frames in range should be selected."""
        points = _make_gps_points(5, time_step=1.0)
        samples = [_make_sample(float(i)) for i in range(5)]

        mock_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_parser.extract_samples.return_value = iter(samples)

        result = sample_video._sample_video_stream_by_distance(
            points, mock_parser, sample_distance=0.0
        )

        assert len(result) == 5

    def test_frames_outside_track_range_excluded(self) -> None:
        """Frames outside the GPS track time range should not be selected."""
        # GPS track covers t=2..6
        points = [
            geo.Point(time=p.time + 2.0, lat=p.lat, lon=p.lon, alt=p.alt, angle=p.angle)
            for p in _make_gps_points(5, time_step=1.0)
        ]

        # Samples at t=0..9 — only t=2..6 should be interpolated
        samples = [_make_sample(float(i)) for i in range(10)]

        mock_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_parser.extract_samples.return_value = iter(samples)

        result = sample_video._sample_video_stream_by_distance(
            points, mock_parser, sample_distance=0.0
        )

        for idx in result:
            sample_time = samples[idx].exact_composition_time
            assert 1.999 <= sample_time <= 6.001

    def test_empty_samples(self) -> None:
        """Empty video track should produce no selected frames."""
        points = _make_gps_points(5, time_step=1.0)

        mock_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_parser.extract_samples.return_value = iter([])

        result = sample_video._sample_video_stream_by_distance(
            points, mock_parser, sample_distance=3.0
        )

        assert len(result) == 0


# ---------------------------------------------------------------------------
# A failed distance sample must not look like a successful one
# ---------------------------------------------------------------------------


class TestDistanceSamplingFailsLoudly:
    """
    Distance sampling used to warn and return when it could not read the GPS,
    which left the caller a success exit code, no sample directory and nothing
    to upload -- `video_process` went on to geotag zero files and printed an
    empty summary. Reported for a GoPro whose embedded GPS is all noise, where
    an attached GPX made no difference.
    """

    VIDEO = _PWD.joinpath("data/mock_sample_video/videos/hello.mp4")

    @pytest.fixture
    def unreadable_gps(self, monkeypatch):
        """Every GPS read fails the way a fully filtered noisy track does."""
        error = exceptions.MapillaryGPSNoiseError("GPS is too noisy")
        monkeypatch.setattr(
            sample_video.factory,
            "process",
            lambda paths, options, sources=None: [
                describe_error_metadata(
                    error, filename=paths[0], filetype=FileType.GOPRO
                )
            ],
        )
        return error

    def _sample(self, tmpdir: py.path.local, **kwargs):
        return sample_video.sample_video(
            self.VIDEO, Path(tmpdir), video_sample_distance=2, rerun=True, **kwargs
        )

    def test_it_raises_instead_of_returning(
        self, tmpdir, setup_mock, unreadable_gps, caplog
    ):
        with pytest.raises(exceptions.MapillaryVideoSampleError):
            self._sample(tmpdir)

        # the underlying reason has to reach the user, and is logged per video
        assert "GPS is too noisy" in caplog.text

    def test_it_names_the_flag_that_suppresses_it(
        self, tmpdir, setup_mock, unreadable_gps
    ):
        """
        --skip_process_errors governs the later geotagging stage and does not
        cover sampling, so the message has to name --skip_sample_errors or
        users reach for the wrong flag.
        """
        with pytest.raises(exceptions.MapillaryVideoError) as excinfo:
            self._sample(tmpdir)

        assert "--skip_sample_errors" in str(excinfo.value)

    def test_the_exit_code_is_a_clean_one(self, tmpdir, setup_mock, unreadable_gps):
        """Not a MapillaryUserError means a traceback instead of an exit code."""
        with pytest.raises(exceptions.MapillaryUserError) as excinfo:
            self._sample(tmpdir)

        assert excinfo.value.exit_code == 7

    def test_nothing_is_left_behind(self, tmpdir, setup_mock, unreadable_gps):
        with pytest.raises(exceptions.MapillaryVideoError):
            self._sample(tmpdir)

        assert not Path(tmpdir).joinpath(self.VIDEO.name).exists()

    def test_skip_sample_errors_still_tolerates_it(
        self, tmpdir, setup_mock, unreadable_gps
    ):
        """The opt-out that several existing callers rely on."""
        self._sample(tmpdir, skip_sample_errors=True)

    def test_the_summary_counts_it_by_its_own_type(
        self, tmpdir, setup_mock, unreadable_gps, caplog
    ):
        with pytest.raises(exceptions.MapillaryVideoSampleError):
            self._sample(tmpdir)

        assert "1 MapillaryGPSNoiseError" in caplog.text

    def test_an_empty_track_is_also_an_error(self, tmpdir, setup_mock, monkeypatch):
        """Previously an assert, so it vanished under `python -O`."""
        monkeypatch.setattr(
            sample_video.factory,
            "process",
            lambda paths, options, sources=None: [
                VideoMetadata(
                    filename=paths[0], filesize=0, filetype=FileType.GOPRO, points=[]
                )
            ],
        )

        with pytest.raises(exceptions.MapillaryVideoError):
            self._sample(tmpdir)

    def test_a_missing_video_stream_is_also_an_error(
        self, tmpdir, setup_mock, monkeypatch
    ):
        monkeypatch.setattr(
            sample_video.factory,
            "process",
            lambda paths, options, sources=None: [
                VideoMetadata(
                    filename=paths[0],
                    filesize=0,
                    filetype=FileType.GOPRO,
                    points=_make_gps_points(3, time_step=1.0),
                )
            ],
        )
        monkeypatch.setattr(
            ffmpeglib.Probe, "probe_video_with_max_resolution", lambda _self: None
        )

        with pytest.raises(exceptions.MapillaryVideoError):
            self._sample(tmpdir)


# ---------------------------------------------------------------------------
# sample_video() parameter validation & rerun
# ---------------------------------------------------------------------------


class TestSampleVideoNegativeDistance:
    """Test sample_video() with invalid parameters."""

    def test_negative_distance_raises(self, tmp_path: Path) -> None:
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        (video_dir / "test.mp4").touch()

        with pytest.raises(exceptions.MapillaryBadParameterError):
            sample_video.sample_video(
                video_import_path=video_dir,
                import_path=tmp_path / "output",
                video_sample_distance=1.0,
                video_sample_interval=1.0,
            )


@pytest.mark.parametrize("ratio", [0, -1, float("nan")])
def test_a_duration_ratio_must_be_positive(tmp_path: Path, ratio: float) -> None:
    """It divides the GPS time of a video without a GPS clock."""
    with pytest.raises(exceptions.MapillaryBadParameterError):
        sample_video.sample_video(
            _PWD.joinpath("data/mock_sample_video/videos/hello.mp4"),
            tmp_path,
            video_duration_ratio=ratio,
        )


class TestSampleVideoRerun:
    """Test rerun behavior of sample_video."""

    def test_skip_existing_samples_without_rerun(self, tmp_path: Path) -> None:
        """Existing sample directories should be skipped without --rerun."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        (video_dir / "test.mp4").touch()

        output_dir = tmp_path / "output"
        sample_dir = output_dir / "test.mp4"
        sample_dir.mkdir(parents=True)
        (sample_dir / "frame_000001.jpg").touch()

        with mock.patch.object(
            sample_video, "_sample_single_video_by_distance"
        ) as mock_sample:
            sample_video.sample_video(
                video_import_path=video_dir,
                import_path=output_dir,
                rerun=False,
            )
            mock_sample.assert_not_called()

    def test_rerun_removes_existing_and_resamples(self, tmp_path: Path) -> None:
        """With --rerun, existing sample directories should be removed."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        (video_dir / "test.mp4").touch()

        output_dir = tmp_path / "output"
        sample_dir = output_dir / "test.mp4"
        sample_dir.mkdir(parents=True)
        marker = sample_dir / "old_frame.jpg"
        marker.touch()

        with mock.patch.object(
            sample_video, "_sample_single_video_by_distance"
        ) as mock_sample:
            sample_video.sample_video(
                video_import_path=video_dir,
                import_path=output_dir,
                rerun=True,
            )
            assert not marker.exists()
            mock_sample.assert_called_once()


# ---------------------------------------------------------------------------
# Distance-based sampling: integration tests with mocked ffmpeg and geotag
# ---------------------------------------------------------------------------


class TestSampleVideoDistanceIntegration:
    """Integration-style tests for the distance-based sampling path."""

    def _setup_mocks(
        self,
        tmp_path: Path,
        video_path: Path,
        num_gps_points: int = 10,
        gps_points: T.Sequence[geo.Point] | None = None,
        sample_times: T.Sequence[float] | None = None,
        # The index of the source that reads the track, of those tried
        read_by: int = 0,
    ) -> dict[str, T.Any]:
        """Set up all the mocks needed for _sample_single_video_by_distance."""
        probe_output = _load_probe_output()
        if gps_points is None:
            gps_points = _make_gps_points(num_gps_points, time_step=1.0)
        num_gps_points = len(gps_points)
        if sample_times is None:
            sample_times = [float(i) for i in range(num_gps_points)]

        video_metadata = VideoMetadata(
            filename=video_path,
            filetype=FileType.CAMM,
            points=gps_points,
            make="TestMake",
            model="TestModel",
        )

        video_samples = [_make_sample(time) for time in sample_times]

        mock_track_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_track_parser.extract_samples.return_value = iter(video_samples)

        mock_moov_parser = mock.MagicMock(spec=mp4_sample_parser.MovieBoxParser)
        mock_moov_parser.extract_track_at.return_value = mock_track_parser

        patches = {}

        # Mock FFMPEG: instance methods are mocked, classmethods delegate to real
        def fake_extract_frames(
            video_path: Path,
            sample_dir: Path,
            frame_indices: set[int],
            stream_specifier: str = "v",
            sample_aspect_ratio: str | None = None,
        ) -> None:
            _create_fake_frames(
                sample_dir,
                video_path.stem,
                stream_specifier,
                len(frame_indices),
            )

        mock_ffmpeg_instance = mock.MagicMock(spec=ffmpeglib.FFMPEG)
        mock_ffmpeg_instance.probe_format_and_streams.return_value = probe_output
        mock_ffmpeg_instance.extract_specified_frames.side_effect = fake_extract_frames

        mock_ffmpeg_class = mock.MagicMock()
        mock_ffmpeg_class.return_value = mock_ffmpeg_instance
        mock_ffmpeg_class.sort_selected_samples = ffmpeglib.FFMPEG.sort_selected_samples
        mock_ffmpeg_class.iterate_samples = ffmpeglib.FFMPEG.iterate_samples
        mock_ffmpeg_class._extract_stream_frame_idx = (
            ffmpeglib.FFMPEG._extract_stream_frame_idx
        )
        mock_ffmpeg_class._validate_stream_specifier = (
            ffmpeglib.FFMPEG._validate_stream_specifier
        )
        mock_ffmpeg_class.FRAME_EXT = ffmpeglib.FFMPEG.FRAME_EXT

        patches["ffmpeg_cls"] = mock.patch(
            "mapillary_tools.sample_video.ffmpeglib.FFMPEG",
            mock_ffmpeg_class,
        )

        def fake_process(paths, options, sources=None):
            if sources is not None:
                sources[paths[0]] = options[read_by]
            return [video_metadata]

        patches["geotag_cls"] = mock.patch(
            "mapillary_tools.sample_video.factory.process",
            side_effect=fake_process,
        )

        patches["moov_parse"] = mock.patch.object(
            mp4_sample_parser.MovieBoxParser,
            "parse_file",
            return_value=mock_moov_parser,
        )

        return {
            "patches": patches,
            "gps_points": gps_points,
            "video_metadata": video_metadata,
        }

    def test_single_video_file(self, tmp_path: Path) -> None:
        """sample_video with a single video file produces sample frames."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        mocks = self._setup_mocks(tmp_path, video_file)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
            )

        sample_dir = output_dir / "test.mp4"
        assert sample_dir.is_dir()

        frames = list(sample_dir.glob("*.jpg"))
        assert len(frames) > 0

        exif = exif_read.ExifRead(frames[0])
        assert exif.extract_lon_lat() is not None
        assert exif.extract_capture_time() is not None

    def test_video_directory(self, tmp_path: Path) -> None:
        """sample_video with a directory processes all videos."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        (video_dir / "clip1.mp4").touch()
        (video_dir / "clip2.mp4").touch()
        output_dir = tmp_path / "output"

        with mock.patch.object(
            sample_video, "_sample_single_video_by_distance"
        ) as mock_sample:
            sample_video.sample_video(
                video_import_path=video_dir,
                import_path=output_dir,
                video_sample_distance=3.0,
            )
            assert mock_sample.call_count == 2

    def test_custom_start_time(self, tmp_path: Path, caplog) -> None:
        """sample_video with video_start_time override uses the given time."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        mocks = self._setup_mocks(tmp_path, video_file)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
                video_start_time="2023_06_15_12_00_00_000",
            )

        sample_dir = output_dir / "test.mp4"
        frames = list(sample_dir.glob("*.jpg"))
        assert len(frames) > 0

        exif = exif_read.ExifRead(frames[0])
        capture_time = exif.extract_capture_time()
        assert capture_time is not None
        assert capture_time.year == 2023
        assert capture_time.month == 6
        assert capture_time.day == 15
        assert "Ignoring --video_start_time" not in caplog.text

    def test_the_gps_clock_wins_over_the_options(self, tmp_path: Path, caplog) -> None:
        """
        A track with a GPS clock stamps the frames at its timestamps and paces
        the video, so --video_start_time and --video_duration_ratio are
        ignored, which is said rather than done silently
        """
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        gps_start_time = datetime.datetime(
            2021, 3, 1, 8, 0, 0, tzinfo=datetime.timezone.utc
        )
        gps_points = [
            telemetry.GPSPoint(
                time=p.time,
                lat=p.lat,
                lon=p.lon,
                alt=p.alt,
                angle=p.angle,
                epoch_time=gps_start_time.timestamp() + p.time,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for p in _make_gps_points(10)
        ]
        mocks = self._setup_mocks(tmp_path, video_file, gps_points=gps_points)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
                video_duration_ratio=0.5,
                video_start_time="2023_06_15_12_00_00_000",
            )

        frames = sorted((output_dir / "test.mp4").glob("*.jpg"))
        assert len(frames) > 0
        assert exif_read.ExifRead(frames[0]).extract_capture_time() == gps_start_time
        assert (
            "Ignoring --video_duration_ratio 0.5 for test.mp4, whose own GPS clock runs at 1x"
            in caplog.text
        )
        assert (
            "Ignoring --video_start_time 2023_06_15_12_00_00_000 for test.mp4"
            in caplog.text
        )

    def test_exif_lat_lon_written(self, tmp_path: Path) -> None:
        """Verify GPS coordinates are written into EXIF of sampled frames."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        mocks = self._setup_mocks(tmp_path, video_file)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
            )

        sample_dir = output_dir / "test.mp4"
        frames = sorted(sample_dir.glob("*.jpg"))
        assert len(frames) > 0

        exif = exif_read.ExifRead(frames[0])
        lon_lat = exif.extract_lon_lat()
        assert lon_lat is not None
        lon, lat = lon_lat
        # First GPS point is at (40.0, -74.0)
        assert abs(lat - 40.0) < 0.01
        assert abs(lon - (-74.0)) < 0.01

    def test_no_frame_within_the_track(self, tmp_path: Path) -> None:
        """
        A track that covers none of the video selects no frames, which is a
        failed sample, not an empty sample directory and a success
        """
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        sample_dir = tmp_path / "output" / "test.mp4"

        mocks = self._setup_mocks(tmp_path, video_file)
        # The frames are at 0s to 9s
        for point in mocks["gps_points"]:
            point.time += 100

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            with pytest.raises(
                exceptions.MapillaryVideoError,
                # how humanize words the time varies between its versions
                match="none of its frames falls within its GPS track, which starts .+ after the video starts",
            ):
                sample_video._sample_single_video_by_distance(
                    video_file, sample_dir, sample_distance=0.0
                )

        assert not sample_dir.exists()

    def test_timestamps_from_creation_time(self, tmp_path: Path) -> None:
        """Without a GPS clock, frames are timestamped from the creation time."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        mocks = self._setup_mocks(tmp_path, video_file)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
            )

        frames = sorted((output_dir / "test.mp4").glob("*.jpg"))
        assert len(frames) == 10
        for idx, frame in enumerate(frames):
            assert exif_read.ExifRead(frame).extract_capture_time() == (
                PROBE_START_TIME + datetime.timedelta(seconds=idx)
            )

    def test_timestamps_from_gps_clock(self, tmp_path: Path) -> None:
        """Frames at points with their own timestamp do not need the creation time."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        gps_start_time = datetime.datetime(
            2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
        )
        gps_points = [
            telemetry.GPSPoint(
                time=p.time,
                lat=p.lat,
                lon=p.lon,
                alt=p.alt,
                angle=p.angle,
                epoch_time=gps_start_time.timestamp() + p.time,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for p in _make_gps_points(10, time_step=1.0)
        ]
        mocks = self._setup_mocks(tmp_path, video_file, gps_points=gps_points)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
            mock.patch.object(
                sample_video,
                "_creation_time_to_start_time",
                side_effect=AssertionError("creation time should not be read"),
            ),
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
            )

        frames = sorted((output_dir / "test.mp4").glob("*.jpg"))
        assert len(frames) == 10
        for idx, frame in enumerate(frames):
            assert exif_read.ExifRead(frame).extract_capture_time() == (
                gps_start_time + datetime.timedelta(seconds=idx)
            )

    def test_timestamps_along_the_gps_timestamps(self, tmp_path: Path) -> None:
        """
        As interval samples are stamped: without a stale first timestamp, which
        is 5 seconds early
        """
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        gps_start_time = datetime.datetime(
            2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
        )
        gps_points = [
            telemetry.GPSPoint(
                time=p.time,
                lat=p.lat,
                lon=p.lon,
                alt=p.alt,
                angle=p.angle,
                epoch_time=gps_start_time.timestamp() + (p.time or -5),
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for p in _make_gps_points(10, time_step=1.0)
        ]
        mocks = self._setup_mocks(tmp_path, video_file, gps_points=gps_points)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
            )

        frames = sorted((output_dir / "test.mp4").glob("*.jpg"))
        assert len(frames) == 10
        for idx, frame in enumerate(frames):
            assert exif_read.ExifRead(frame).extract_capture_time() == (
                gps_start_time + datetime.timedelta(seconds=idx)
            )

    @pytest.mark.parametrize("source", [SourceType.NATIVE, SourceType.GPX])
    def test_a_short_timelapse_at_its_timestamps(
        self, tmp_path: Path, source: SourceType
    ) -> None:
        """
        Over a second of a 12.4x timelapse, too short to measure its rate, the
        rate is 1. Its track, from its own GPS or from a GPX that the straight
        clock of a noisy GoPro MAX placed, still stamps the frames at its
        timestamps, not all within the last second of it
        """
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        sample_dir = tmp_path / "output" / "test.mp4"

        gps_start_time = datetime.datetime(
            2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
        )
        video_times = [seconds / 12.4 for seconds in range(13)]
        gps_points = [
            telemetry.GPSPoint(
                time=video_time,
                lat=40.0 + seconds * 0.0001,
                lon=-74.0,
                alt=None,
                angle=None,
                epoch_time=gps_start_time.timestamp() + seconds,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for seconds, video_time in enumerate(video_times)
        ]
        mocks = self._setup_mocks(
            tmp_path, video_file, gps_points=gps_points, sample_times=video_times
        )

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video._sample_single_video_by_distance(
                video_file,
                sample_dir,
                sample_distance=0.0,
                geotag_options=[SourceOption(source)],
            )

        frames = sorted(sample_dir.glob("*.jpg"))
        capture_times = [
            exif_read.ExifRead(frame).extract_capture_time() for frame in frames
        ]
        assert capture_times == [
            gps_start_time + datetime.timedelta(seconds=seconds)
            for seconds in range(13)
        ]

    def test_a_gpx_track_at_its_timestamps(self, tmp_path: Path) -> None:
        """
        GPX sync placed the track along the video's clock, which gains a
        second over the first half second of video here. Its first timestamp
        is no stale one of the video's own GPS
        """
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        sample_dir = tmp_path / "output" / "test.mp4"

        gps_start_time = datetime.datetime(
            2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
        )
        video_times = [0.0, 0.5, 1.5, 2.5, 3.5, 4.5]
        gps_points = [
            telemetry.GPSPoint(
                time=video_time,
                lat=40.0 + seconds * 0.0001,
                lon=-74.0,
                alt=None,
                angle=None,
                epoch_time=gps_start_time.timestamp() + seconds,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for seconds, video_time in enumerate(video_times)
        ]
        mocks = self._setup_mocks(
            tmp_path, video_file, gps_points=gps_points, sample_times=video_times
        )

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video._sample_single_video_by_distance(
                video_file,
                sample_dir,
                sample_distance=0.0,
                geotag_options=[SourceOption(SourceType.GPX)],
            )

        frames = sorted(sample_dir.glob("*.jpg"))
        capture_times = [
            exif_read.ExifRead(frame).extract_capture_time() for frame in frames
        ]
        assert capture_times == [
            gps_start_time + datetime.timedelta(seconds=seconds) for seconds in range(6)
        ]

    GPS_START_TIME = datetime.datetime(
        2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
    )

    def _file_track(self, video_times, rate: float = 1.0) -> list[geo.Point]:
        """
        The points of a track from a GPX (or NMEA) file as GPX sync places
        them on the video, at video times, keeping their own GPS times, of
        which a timelapse packs **rate** into each second of video
        """
        return [
            telemetry.CAMMGPSPoint(
                time=float(t),
                lat=40.0 + t * 0.001,
                lon=-74.0,
                alt=None,
                angle=None,
                epoch_time=self.GPS_START_TIME.timestamp() + t * rate,
                gps_fix_type=2,
                horizontal_accuracy=0.0,
                vertical_accuracy=0.0,
                velocity_east=0.0,
                velocity_north=0.0,
                velocity_up=0.0,
                speed_accuracy=0.0,
            )
            for t in video_times
        ]

    def _sample_along_a_file_track(
        self,
        tmp_path: Path,
        gps_points: T.Sequence[geo.Point],
        read_by: int = 0,
        **kwargs,
    ) -> list[datetime.datetime | None]:
        """
        Sample a frame a second by distance, the track read by the source at
        index **read_by** of those tried, and read their capture times
        """
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"
        mocks = self._setup_mocks(
            tmp_path,
            video_file,
            gps_points=gps_points,
            sample_times=[float(t) for t in range(int(gps_points[-1].time) + 1)],
            read_by=read_by,
        )

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
                geotag_source_path=tmp_path / "track.gpx",
                **kwargs,
            )

        frames = sorted((output_dir / "test.mp4").glob("*.jpg"))
        return [exif_read.ExifRead(frame).extract_capture_time() for frame in frames]

    # Whatever source follows the one that read the track
    @pytest.mark.parametrize("then", [[], ["native"], ["exiftool_runtime"]])
    @pytest.mark.parametrize("source", ["gpx", "nmea"])
    def test_frames_in_a_gap_of_a_video_track_file_are_left_out(
        self, tmp_path: Path, monkeypatch, caplog, source, then
    ) -> None:
        """
        The track of --video_geotag_source has a gap of 10 seconds, over the
        limit, from 10 to 20 seconds into the video. The frames in it were
        placed across it, as they would be outside the track
        """
        monkeypatch.setattr(sample_video.constants, "MAX_GPX_GAP_SECONDS", 5.0)
        video_times = [*range(11), *range(20, 31)]

        with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
            capture_times = self._sample_along_a_file_track(
                tmp_path,
                self._file_track(video_times),
                video_geotag_source=[source, *then],
            )

        assert capture_times == [
            self.GPS_START_TIME + datetime.timedelta(seconds=t) for t in video_times
        ]
        assert (
            "9 frames of test.mp4 fall in a gap of its GPS track and were left out: "
            "a gap of 10 seconds, from 2021-08-10T06:38:16+00:00 at (40.01, -74.0) "
            "to 2021-08-10T06:38:26+00:00 at (40.02, -74.0)"
        ) in caplog.text

    def test_the_gap_limit_is_in_gps_seconds_in_a_timelapse(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """
        The gap of 2 seconds of video, from 10 to 12 seconds into it, spans 20
        seconds of GPS time at 10x, over the limit
        """
        monkeypatch.setattr(sample_video.constants, "MAX_GPX_GAP_SECONDS", 15.0)
        video_times = [*range(11), *range(12, 21)]

        capture_times = self._sample_along_a_file_track(
            tmp_path,
            self._file_track(video_times, rate=10.0),
            video_geotag_source=["gpx"],
        )

        assert capture_times == [
            self.GPS_START_TIME + datetime.timedelta(seconds=t * 10)
            for t in video_times
        ]

    @pytest.mark.parametrize(
        "kwargs",
        [
            # The geotagging stage places the frames along the track of a file
            # of --geotag_source by their capture times
            {"geotag_source": ["gpx"]},
            # The legacy gopro source geotags them by the GPS of their video
            {"video_geotag_source": ["gpx"], "geotag_source": ["gopro"]},
        ],
    )
    def test_frames_in_a_gap_are_left_where_the_geotagging_stage_places_them(
        self, tmp_path: Path, monkeypatch, kwargs
    ) -> None:
        monkeypatch.setattr(sample_video.constants, "MAX_GPX_GAP_SECONDS", 5.0)

        capture_times = self._sample_along_a_file_track(
            tmp_path, self._file_track([*range(11), *range(20, 31)]), **kwargs
        )

        assert capture_times == [
            self.GPS_START_TIME + datetime.timedelta(seconds=t) for t in range(31)
        ]

    @pytest.mark.parametrize(
        "video_geotag_source",
        # After a GPX that misses the video, or before a GPX
        [["gpx", "native"], ["native", "gpx"]],
    )
    def test_frames_in_a_gap_of_a_track_read_by_the_video_are_kept(
        self, tmp_path: Path, monkeypatch, video_geotag_source
    ) -> None:
        """The video's own track is sampled across its gaps, as without a GPX"""
        monkeypatch.setattr(sample_video.constants, "MAX_GPX_GAP_SECONDS", 5.0)

        capture_times = self._sample_along_a_file_track(
            tmp_path,
            self._file_track([*range(11), *range(20, 31)]),
            read_by=video_geotag_source.index("native"),
            video_geotag_source=video_geotag_source,
        )

        assert capture_times == [
            self.GPS_START_TIME + datetime.timedelta(seconds=t) for t in range(31)
        ]

    def test_timelapse_frames_past_the_end_are_stamped_within_the_track(
        self, tmp_path: Path
    ) -> None:
        """
        The last frame is 0.5 ms of video past the end of the track, which a
        30x timelapse stretches to 15 ms of GPS time. Stamped there, it would
        fall outside the GPX in the geotagging stage, which allows 1 ms.
        """
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        gps_start_time = datetime.datetime(
            2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
        )
        gps_points = [
            telemetry.GPSPoint(
                time=time,
                lat=40.0 + time * 0.001,
                lon=-74.0,
                alt=None,
                angle=None,
                epoch_time=gps_start_time.timestamp() + 30 * time,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for time in [*range(9), 8.9995]
        ]
        mocks = self._setup_mocks(tmp_path, video_file, gps_points=gps_points)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
            )

        frames = sorted((output_dir / "test.mp4").glob("*.jpg"))
        capture_times = [
            exif_read.ExifRead(frame).extract_capture_time() for frame in frames
        ]
        assert capture_times == [
            gps_start_time + datetime.timedelta(seconds=30 * idx) for idx in range(9)
        ] + [gps_start_time + datetime.timedelta(seconds=269.985)]

    def test_frames_past_the_last_timestamp_are_stamped_by_the_clock(
        self, tmp_path: Path
    ) -> None:
        """
        The last three timestamps are stamped 1.5 seconds early, as GoPro
        stamps blocks of points off the straight clock. Clamped to the last
        timestamp, the last frames were all stamped with it
        """
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        gps_start_time = datetime.datetime(
            2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
        )
        gps_points = [
            telemetry.GPSPoint(
                time=float(time),
                lat=40.0 + time * 0.001,
                lon=-74.0,
                alt=None,
                angle=None,
                epoch_time=gps_start_time.timestamp()
                + time
                - (1.5 if 18 <= time else 0),
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for time in range(21)
        ]
        mocks = self._setup_mocks(tmp_path, video_file, gps_points=gps_points)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
            )

        frames = sorted((output_dir / "test.mp4").glob("*.jpg"))
        capture_times = [
            exif_read.ExifRead(frame).extract_capture_time() for frame in frames
        ]
        assert capture_times == [
            gps_start_time + datetime.timedelta(seconds=idx) for idx in range(21)
        ]


class TestProbeVideo:
    """ffprobe fails on a video that has no moov box, such as one cut short"""

    VIDEO = _PWD.parent.joinpath("data/videos/sample-5s.mp4")

    class FailingFFMPEG(ffmpeglib.FFMPEG):
        def probe_format_and_streams(self, video_path: Path) -> ffmpeglib.ProbeOutput:
            raise ffmpeglib.FFmpegCalledProcessError(
                subprocess.CalledProcessError(1, ["ffprobe", str(video_path)])
            )

    def test_a_video_without_a_moov_box_is_invalid(self, tmp_path: Path):
        video_path = tmp_path / "truncated.mp4"
        # Its moov box follows the media data
        video_path.write_bytes(self.VIDEO.read_bytes()[:100_000])

        with pytest.raises(exceptions.MapillaryInvalidVideoError) as excinfo:
            sample_video._probe_video(self.FailingFFMPEG(), video_path)

        # As process reports it
        assert str(excinfo.value) == "Invalid video: unable find box at path [b'moov']"

    def test_any_other_failure_is_raised_as_it_is(self):
        with pytest.raises(ffmpeglib.FFmpegCalledProcessError):
            sample_video._probe_video(self.FailingFFMPEG(), self.VIDEO)


class TestFailuresAreReportedTogether:
    """
    A video that fails to sample does not stop the others. They are sampled,
    the failures are summarized by type, and one error naming
    --skip_sample_errors is raised at the end, as the process command does
    with --skip_process_errors. Raising on the first failure left the samples
    of the videos before it unprocessed, and which videos those were depended
    on the order the filesystem listed them in.
    """

    VIDEO = _PWD.joinpath("data/mock_sample_video/videos/hello.mp4")

    @pytest.fixture
    def video_dir(self, tmp_path: Path, monkeypatch) -> Path:
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        videos = [video_dir / name for name in ["c.mp4", "a.mp4", "b.mp4"]]
        for video in videos:
            video.touch()
        # Listed out of order, as a filesystem may list them
        monkeypatch.setattr(
            sample_video.utils, "find_videos", lambda *args, **kwargs: videos
        )
        return video_dir

    @pytest.fixture
    def attempted(self, monkeypatch) -> list[str]:
        """
        Sample a video by creating its sample directory, unless it is named
        a.mp4 (no GPS) or b.mp4 (unreadable)
        """
        attempted: list[str] = []

        def fake_sample(video_path: Path, sample_dir: Path, **kwargs) -> None:
            attempted.append(video_path.name)
            if video_path.name == "a.mp4":
                raise exceptions.MapillaryVideoGPSNotFoundError("No GPS data found")
            if video_path.name == "b.mp4":
                raise exceptions.MapillaryVideoError("Unreadable")
            sample_dir.mkdir(parents=True)

        monkeypatch.setattr(
            sample_video, "_sample_single_video_by_distance", fake_sample
        )
        return attempted

    def test_every_video_is_sampled_in_order(
        self, tmp_path: Path, video_dir: Path, attempted: list[str]
    ):
        with pytest.raises(exceptions.MapillaryVideoSampleError):
            sample_video.sample_video(video_dir, tmp_path / "output")

        assert attempted == ["a.mp4", "b.mp4", "c.mp4"]
        assert (tmp_path / "output" / "c.mp4").is_dir()

    def test_one_error_names_the_flag(
        self, tmp_path: Path, video_dir: Path, attempted: list[str]
    ):
        """
        --skip_process_errors governs the later geotagging stage and does not
        cover sampling, so the message has to name --skip_sample_errors or
        users reach for the wrong flag.
        """
        with pytest.raises(exceptions.MapillaryVideoSampleError) as excinfo:
            sample_video.sample_video(video_dir, tmp_path / "output")

        assert str(excinfo.value) == (
            "Failed to sample 2 videos. To skip these errors, specify --skip_sample_errors"
        )

    def test_the_summary_counts_failures_by_type(
        self, tmp_path: Path, video_dir: Path, attempted: list[str], caplog
    ):
        caplog.set_level(logging.INFO)
        with pytest.raises(exceptions.MapillaryVideoSampleError):
            sample_video.sample_video(video_dir, tmp_path / "output")

        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert f"Failed to sample {video_dir / 'a.mp4'}: No GPS data found" in errors
        assert f"Failed to sample {video_dir / 'b.mp4'}: Unreadable" in errors
        assert "\t1 MapillaryVideoGPSNotFoundError" in errors
        assert "\t1 MapillaryVideoError" in errors
        assert "3 videos found" in caplog.text
        assert "\t1 sampled" in caplog.text

    def test_skip_sample_errors_downgrades_them_to_warnings(
        self, tmp_path: Path, video_dir: Path, attempted: list[str], caplog
    ):
        sample_video.sample_video(
            video_dir, tmp_path / "output", skip_sample_errors=True
        )

        assert attempted == ["a.mp4", "b.mp4", "c.mp4"]
        assert not [r for r in caplog.records if r.levelname == "ERROR"]
        assert "\t1 MapillaryVideoGPSNotFoundError" in caplog.text

    def test_the_import_path_exists_even_if_nothing_samples(
        self, tmp_path: Path, attempted: list[str]
    ):
        """
        video_process runs the process command on the import path next, which
        fails on a missing one: skipping every video used to end in "Import
        file or directory not found"
        """
        video = tmp_path / "a.mp4"
        video.touch()

        sample_video.sample_video(video, tmp_path / "output", skip_sample_errors=True)

        assert (tmp_path / "output").is_dir()
        assert not list((tmp_path / "output").iterdir())

    def test_unreadable_start_time_by_interval(
        self, tmpdir, setup_mock, monkeypatch, caplog
    ):
        monkeypatch.setattr(
            sample_video, "_extract_video_start_time", lambda *args: None
        )

        with pytest.raises(exceptions.MapillaryVideoSampleError):
            sample_video.sample_video(
                self.VIDEO,
                Path(tmpdir),
                rerun=True,
                video_sample_distance=-1,
                video_sample_interval=2,
            )

        assert "Unable to extract video start time" in caplog.text

    def test_unreadable_start_time_by_distance(
        self, tmpdir, setup_mock, monkeypatch, caplog
    ):
        """
        Distance sampling looks the start time up only for the frames at
        points without an absolute time, and fails if it cannot be found
        """
        # plain points: no GPS clock to take the start time from
        points = _make_gps_points(4, time_step=1.0)
        monkeypatch.setattr(
            sample_video.factory,
            "process",
            lambda paths, options, sources=None: [
                VideoMetadata(
                    filename=paths[0],
                    filesize=1,
                    filetype=FileType.VIDEO,
                    points=points,
                )
            ],
        )
        monkeypatch.setattr(
            ffmpeglib.Probe,
            "probe_video_with_max_resolution",
            lambda _self: {"index": 0},
        )
        monkeypatch.setattr(
            mp4_sample_parser.MovieBoxParser, "parse_file", mock.MagicMock()
        )
        monkeypatch.setattr(
            sample_video,
            "_sample_video_stream_by_distance",
            lambda *args: {0: (mock.MagicMock(), points[0])},
        )
        monkeypatch.setattr(
            sample_video, "_creation_time_to_start_time", lambda *args: None
        )

        with pytest.raises(exceptions.MapillaryVideoSampleError):
            sample_video.sample_video(
                self.VIDEO, Path(tmpdir), rerun=True, video_sample_distance=2
            )

        assert "Unable to extract video start time" in caplog.text

    def test_a_missing_ffmpeg_is_still_fatal(self, tmpdir, setup_mock, monkeypatch):
        """
        FFmpegNotFoundError fails every video alike, so it is raised at once,
        --skip_sample_errors or not, and its message must not offer the flag
        """

        def boom(*args, **kwargs):
            raise ffmpeglib.FFmpegNotFoundError("ffmpeg not found")

        monkeypatch.setattr(MOCK_FFMPEG, "extract_frames_by_interval", boom)

        with pytest.raises(exceptions.MapillaryFFmpegNotFoundError) as excinfo:
            sample_video.sample_video(
                self.VIDEO,
                Path(tmpdir),
                video_sample_distance=-1,
                video_sample_interval=2,
                rerun=True,
                skip_sample_errors=True,
            )

        assert "--skip_sample_errors" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Distance sampling honours --geotag_source
# ---------------------------------------------------------------------------


class TestGeotagSourceReachesDistanceSampling:
    """
    Distance sampling read the video's own telemetry directly, bypassing the
    geotag factory, so --geotag_source was ignored: a GPX attached to rescue a
    camera whose embedded GPS is unusable never got a chance to supply the
    positions the sampler picks frames with.
    """

    def test_no_sources_requested_means_native_only(self):
        """
        Not DEFAULT_GEOTAG_SOURCE_OPTIONS: that chain continues on to
        exiftool_runtime, whose parser cannot see every field the noise filter
        rejects on, so it would accept tracks the native parser refuses.
        """
        options = sample_video._parse_geotag_options(
            None, None, None, Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [SourceType.NATIVE]

    def test_requested_source_is_passed_through(self):
        options = sample_video._parse_geotag_options(
            ["gpx"], Path("/data/track.gpx"), None, Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [SourceType.GPX]
        assert options[0].source_path is not None
        assert options[0].source_path.source_path == Path("/data/track.gpx")

    def test_video_geotag_source_is_honoured_too(self):
        options = sample_video._parse_geotag_options(
            None, Path("/data/track.gpx"), ["gpx"], Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [SourceType.GPX]

    @pytest.mark.parametrize("source", ["exiftool_xml", "gpx"])
    def test_without_a_path_sources_get_the_video_import_path(self, source):
        """
        As when the frames are geotagged. That is how exiftool_xml finds the
        XML files in the video directory; a GPX gets no sidecar lookup.
        """
        options = sample_video._parse_geotag_options(
            [source], None, None, Path("/data/videos")
        )

        assert options[0].source_path is not None
        assert options[0].source_path.source_path == Path("/data/videos")

    def test_without_a_path_exiftool_xml_gets_its_default_pattern(self):
        """
        As in process: the XML named after each video beside it, or else the
        XMLs in the video import path. With only the import path, it read those
        XMLs only, matched by the paths in them
        """
        [option] = sample_video._parse_geotag_options(
            None, None, ["exiftool_xml"], Path("/data/videos")
        )

        assert option.source_path is not None
        assert option.source_path.pattern == "%g.xml"
        assert option.source_path.source_path == Path("/data/videos")

    @pytest.mark.parametrize("source", ["gpx", "native"])
    def test_without_a_path_other_sources_get_no_pattern(self, source):
        [option] = sample_video._parse_geotag_options(
            [source], None, None, Path("/data/videos")
        )

        assert option.source_path is not None
        assert option.source_path.pattern is None

    def test_exiftool_xml_with_a_path_gets_no_pattern(self):
        [option] = sample_video._parse_geotag_options(
            None, Path("/data/xmls"), ["exiftool_xml"], Path("/data/videos")
        )

        assert option.source_path is not None
        assert option.source_path.pattern is None
        assert option.source_path.source_path == Path("/data/xmls")

    def test_without_a_path_a_pattern_is_kept(self):
        """
        SourcePathOption.resolve() returns a source_path before trying the
        pattern, so filling in the import path would read the video itself as
        the XML.
        """
        options = sample_video._parse_geotag_options(
            None,
            None,
            ['{"source": "exiftool_xml", "pattern": "%g.xml"}'],
            Path("/data/videos/v.mp4"),
        )

        assert options[0].source_path is not None
        assert options[0].source_path.source_path is None
        assert options[0].source_path.pattern == "%g.xml"

    def test_chained_sources_are_preserved(self):
        options = sample_video._parse_geotag_options(
            ["native", "gpx"], Path("/data/track.gpx"), None, Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [
            SourceType.NATIVE,
            SourceType.GPX,
        ]

    def test_the_sampler_asks_the_factory_for_them(
        self, tmpdir, setup_mock, monkeypatch
    ):
        """The options reach factory.process() rather than being dropped."""
        seen: list = []
        points = _make_gps_points(4, time_step=1.0)

        def fake_process(paths, options, sources=None):
            seen.append(list(options))
            return [
                VideoMetadata(
                    filename=paths[0],
                    filesize=1,
                    filetype=FileType.GOPRO,
                    points=points,
                )
            ]

        monkeypatch.setattr(sample_video.factory, "process", fake_process)
        # stop after the metadata is read; the rest needs real ffmpeg
        monkeypatch.setattr(
            ffmpeglib.Probe, "probe_video_with_max_resolution", lambda _self: None
        )

        with pytest.raises(exceptions.MapillaryVideoError):
            sample_video.sample_video(
                _PWD.joinpath("data/mock_sample_video/videos/hello.mp4"),
                Path(tmpdir),
                video_sample_distance=2,
                rerun=True,
                geotag_source=["gpx"],
                geotag_source_path=Path("/data/track.gpx"),
            )

        assert len(seen) == 1
        assert [option.source for option in seen[0]] == [SourceType.GPX]


class TestSourcesThatCannotReadVideos:
    """
    exif and the legacy gopro/blackvue/camm sources have no video extractor,
    so process() returned no metadata for the video and the sampler failed an
    assert, for a video it used to sample by its own GPS.
    """

    @pytest.mark.parametrize("source", ["exif", "gopro", "blackvue", "camm"])
    def test_sampling_falls_back_to_the_video_gps(self, source):
        options = sample_video._parse_geotag_options(
            [source], Path("/data/track"), None, Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [SourceType.NATIVE]

    def test_nmea_reads_videos(self):
        options = sample_video._parse_geotag_options(
            ["nmea"], Path("/data/track.nmea"), None, Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [SourceType.NMEA]

    def test_they_are_dropped_from_a_chain(self):
        options = sample_video._parse_geotag_options(
            ["exif", "gpx"], Path("/data/track.gpx"), None, Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [SourceType.GPX]

    def test_a_source_limited_to_images_is_dropped(self):
        options = sample_video._parse_geotag_options(
            ['{"source": "gpx", "filetypes": ["image"]}'],
            Path("/data/track.gpx"),
            None,
            Path("/data/v.mp4"),
        )

        assert [option.source for option in options] == [SourceType.NATIVE]


class TestVideoStartTimeReachesTheGPX:
    """
    A GPX on a video without GPS was assumed to start with the video, and
    --video_start_time was ignored, so every clip of a drive sampled the first
    minutes of its GPX, and was stamped with their times.
    """

    def test_every_option_carries_it(self):
        video_sync = VideoSyncOption(start_time=1_700_000_000.0)

        for sources in [None, ["gpx"], ["exif"]]:
            options = sample_video._parse_geotag_options(
                sources, Path("/data/track.gpx"), None, Path("/data/v.mp4"), video_sync
            )
            assert all(option.video_sync is video_sync for option in options)

    def test_sample_video_passes_it_on(self, tmpdir, setup_mock, monkeypatch):
        seen: list = []

        def fake_process(paths, options, sources=None):
            seen.extend(options)
            return [
                VideoMetadata(
                    filename=paths[0],
                    filesize=1,
                    filetype=FileType.VIDEO,
                    points=_make_gps_points(4, time_step=1.0),
                )
            ]

        monkeypatch.setattr(sample_video.factory, "process", fake_process)
        # stop after the metadata is read; the rest needs real ffmpeg
        monkeypatch.setattr(
            ffmpeglib.Probe, "probe_video_with_max_resolution", lambda _self: None
        )

        with pytest.raises(exceptions.MapillaryVideoError):
            sample_video.sample_video(
                _PWD.joinpath("data/mock_sample_video/videos/hello.mp4"),
                Path(tmpdir),
                video_sample_distance=2,
                rerun=True,
                video_start_time="2025_03_14_07_00_30_000",
                geotag_source=["gpx"],
                geotag_source_path=Path("/data/track.gpx"),
            )

        expected = datetime.datetime(
            2025, 3, 14, 7, 0, 30, tzinfo=datetime.timezone.utc
        ).timestamp()
        assert seen[0].video_sync == VideoSyncOption(start_time=expected)

    def test_sample_video_passes_the_interpolation_options_on(
        self, tmpdir, setup_mock, monkeypatch
    ):
        """video_process registers them for its geotagging stage."""
        seen: list = []

        def fake_process(paths, options, sources=None):
            seen.extend(options)
            return [
                VideoMetadata(
                    filename=paths[0],
                    filesize=1,
                    filetype=FileType.VIDEO,
                    points=_make_gps_points(4, time_step=1.0),
                )
            ]

        monkeypatch.setattr(sample_video.factory, "process", fake_process)
        monkeypatch.setattr(
            ffmpeglib.Probe, "probe_video_with_max_resolution", lambda _self: None
        )

        with pytest.raises(exceptions.MapillaryVideoError):
            sample_video.sample_video(
                _PWD.joinpath("data/mock_sample_video/videos/hello.mp4"),
                Path(tmpdir),
                video_sample_distance=2,
                rerun=True,
                geotag_source=["gpx"],
                geotag_source_path=Path("/data/track.gpx"),
                interpolation_offset_time=2.5,
                interpolation_use_gpx_start_time=True,
            )

        assert seen[0].interpolation == InterpolationOption(
            offset_time=2.5, use_gpx_start_time=True
        )

    def test_the_interpolation_options_of_a_source_win(self):
        """As they do when the geotagging stage geotags the frames."""
        options = sample_video._parse_geotag_options(
            ['{"source": "gpx", "interpolation_offset_time": 1}'],
            Path("/data/track.gpx"),
            None,
            Path("/data/v.mp4"),
            VideoSyncOption(),
            InterpolationOption(offset_time=2.5),
        )

        assert options[0].interpolation == InterpolationOption(offset_time=1)

    def test_without_it_the_start_time_is_left_unknown(self):
        """
        A video without a GPS clock would get its start time from its creation
        time, which cameras stamp at the start or the end of the recording.
        """
        options = sample_video._parse_geotag_options(
            ["gpx"], Path("/data/track.gpx"), None, Path("/data/v.mp4"), None
        )

        assert options[0].video_sync is None


class TestTrackThatMissesTheVideo:
    def test_it_fails_instead_of_writing_an_empty_sample_directory(
        self, tmpdir, setup_mock, monkeypatch, caplog
    ):
        """
        A GPX placed by a wrong --video_start_time selects no frames. The
        video counts as failed, and the log says why.
        """
        points = _make_gps_points(4, time_step=1.0)
        for point in points:
            point.time -= 7200
        monkeypatch.setattr(
            sample_video.factory,
            "process",
            lambda paths, options, sources=None: [
                VideoMetadata(
                    filename=paths[0],
                    filesize=1,
                    filetype=FileType.VIDEO,
                    points=points,
                )
            ],
        )
        monkeypatch.setattr(
            ffmpeglib.Probe,
            "probe_video_with_max_resolution",
            lambda _self: {"index": 0},
        )
        monkeypatch.setattr(
            mp4_sample_parser.MovieBoxParser, "parse_file", mock.MagicMock()
        )
        monkeypatch.setattr(
            sample_video, "_sample_video_stream_by_distance", lambda *args: {}
        )

        with pytest.raises(exceptions.MapillaryVideoSampleError):
            sample_video.sample_video(
                _PWD.joinpath("data/mock_sample_video/videos/hello.mp4"),
                Path(tmpdir),
                video_sample_distance=2,
                rerun=True,
            )

        assert "none of its frames falls within its GPS track" in caplog.text
        assert "before the video starts" in caplog.text
        assert not Path(tmpdir).joinpath("hello.mp4").exists()


class TestSampleSourcesPath:
    """
    The sources that the geotagging stage geotags the samples by read the
    video import path when --geotag_source_path is not given. A source with a
    path of its own was warned to ignore --geotag_source_path, although it was
    not given
    """

    _WARNING = "The option --geotag_source_path is ignored"

    @staticmethod
    def _sources(geotag_source_path: Path | None) -> list[SourceOption]:
        options = sample_video._parse_sample_sources(
            [
                '{"source": "gpx", "source_path": "/data/track.gpx"}',
                "nmea",
            ],
            geotag_source_path,
            Path("/data/videos"),
            InterpolationOption(),
        )
        assert options is not None
        return options

    def test_not_warned_without_geotag_source_path(self, caplog):
        with caplog.at_level(logging.WARNING):
            gpx, nmea = self._sources(None)

        assert self._WARNING not in caplog.text
        assert gpx.source_path is not None
        assert gpx.source_path.source_path == Path("/data/track.gpx")
        assert nmea.source_path is not None
        assert nmea.source_path.source_path == Path("/data/videos")

    def test_warned_when_given_and_ignored(self, caplog):
        with caplog.at_level(logging.WARNING):
            gpx, nmea = self._sources(Path("/data/other.gpx"))

        assert caplog.text.count(self._WARNING) == 1
        assert gpx.source_path is not None
        assert gpx.source_path.source_path == Path("/data/track.gpx")
        assert nmea.source_path is not None
        assert nmea.source_path.source_path == Path("/data/other.gpx")


def _symlink(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as ex:
        pytest.skip(f"Cannot create symbolic links here: {ex}")


def test_a_symlinked_video_is_sampled_into_a_folder_named_after_the_link(
    tmp_path: Path,
):
    """
    A link in the folder to a video outside it crashed with "is not in the
    subpath of", and a link given itself was sampled into a folder named after
    the video it links to, while its samples were named after the link
    """
    target = tmp_path / "elsewhere" / "video.mp4"
    target.parent.mkdir()
    target.write_bytes(b"")
    videos = tmp_path / "videos"
    videos.mkdir()
    _symlink(videos / "link.mp4", target)
    out = tmp_path / "out"

    assert sample_video.find_sample_dirs(videos, out) == [out / "link.mp4"]
    assert sample_video.find_sample_dirs(videos / "link.mp4", out) == [out / "link.mp4"]

    # Two links to one video are still sampled once, by either link
    _symlink(videos / "link2.mp4", target)
    [sample_dir] = sample_video.find_sample_dirs(videos, out)
    assert sample_dir in [out / "link.mp4", out / "link2.mp4"]
