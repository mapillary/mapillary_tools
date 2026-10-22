# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import datetime
import os
import shutil
import typing as T
from pathlib import Path

import pytest
from mapillary_tools import geo, telemetry, types
from mapillary_tools.exif_write import ExifEdit
from mapillary_tools.geotag.geotag_images_from_video import GeotagImagesFromVideo

_PWD = Path(os.path.dirname(os.path.abspath(__file__)))

START_TIME = datetime.datetime(2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc)


def _video_metadata(
    video_path: Path, gps_seconds: T.Sequence[float]
) -> types.VideoMetadata:
    # One point per second of video, at gps_seconds[i] from START_TIME
    points = [
        telemetry.GPSPoint(
            time=float(i),
            lat=40.0 + i * 0.0001,
            lon=-74.0,
            alt=None,
            angle=None,
            epoch_time=START_TIME.timestamp() + seconds,
            fix=None,
            precision=None,
            ground_speed=None,
        )
        for i, seconds in enumerate(gps_seconds)
    ]
    return types.VideoMetadata(
        filename=video_path,
        filetype=types.FileType.GOPRO,
        points=T.cast(T.List[geo.Point], points),
    )


def _sample(sample_dir: Path, idx: int, capture_time: datetime.datetime) -> Path:
    sample_path = sample_dir / f"hello_v_{idx:06d}.jpg"
    shutil.copyfile(_PWD / "data/test_exif.jpg", sample_path)
    exif_edit = ExifEdit(sample_path)
    exif_edit.add_date_time_original(capture_time)
    exif_edit.add_gps_datetime(capture_time)
    exif_edit.write()
    return sample_path


@pytest.mark.parametrize("rate", [1.0, 10.0])
def test_samples_are_placed_by_their_capture_times(tmp_path: Path, rate: float):
    video_path = tmp_path / "hello.mp4"
    sample_dir = tmp_path / "samples" / "hello.mp4"
    sample_dir.mkdir(parents=True)

    # A sample every 2 seconds of video, stamped with its capture time, which
    # a timelapse spaces **rate** times as far apart
    samples = [
        _sample(
            sample_dir, k + 1, START_TIME + datetime.timedelta(seconds=2 * k * rate)
        )
        for k in range(4)
    ]

    metadatas = GeotagImagesFromVideo(
        [_video_metadata(video_path, [rate * i for i in range(10)])], num_processes=0
    ).to_description(samples)

    lat_by_name = {}
    for metadata in metadatas:
        assert isinstance(metadata, types.ImageMetadata), metadata
        lat_by_name[metadata.filename.name] = metadata.lat
    assert lat_by_name == {
        sample.name: pytest.approx(40.0 + 2 * k * 0.0001)
        for k, sample in enumerate(samples)
    }


def test_timelapse_samples_are_placed_by_the_gps_timestamps(tmp_path: Path):
    """
    Distance samples are stamped with the GPS time of their video time. A
    GoPro MAX timelapse can stamp its first point seconds early, and its clock
    keeps no one rate, so timed at one rate the track placed the samples off,
    and the last ones past its end.
    """
    video_path = tmp_path / "hello.mp4"
    sample_dir = tmp_path / "samples" / "hello.mp4"
    sample_dir.mkdir(parents=True)

    # 10x, but the first timestamp 3 seconds early and the clock speeding up
    gps_seconds = [0.0] + [3 + 10 * i + 0.1 * i * i for i in range(1, 10)]

    def stamped(video_time: float) -> datetime.datetime:
        i = int(video_time)
        seconds = gps_seconds[i]
        if i + 1 < len(gps_seconds):
            seconds += (gps_seconds[i + 1] - gps_seconds[i]) * (video_time - i)
        return START_TIME + datetime.timedelta(seconds=seconds)

    video_times = [0.0, 0.5, 2.0, 4.5, 8.0, 9.0]
    samples = [
        _sample(sample_dir, k + 1, stamped(video_time))
        for k, video_time in enumerate(video_times)
    ]

    metadatas = GeotagImagesFromVideo(
        [_video_metadata(video_path, gps_seconds)], num_processes=0
    ).to_description(samples)

    lat_by_name = {}
    for metadata in metadatas:
        assert isinstance(metadata, types.ImageMetadata), metadata
        lat_by_name[metadata.filename.name] = metadata.lat
    assert lat_by_name == {
        sample.name: pytest.approx(40.0 + video_time * 0.0001)
        for sample, video_time in zip(samples, video_times)
    }


def test_samples_are_placed_by_their_own_video(tmp_path: Path):
    """
    Each video placed the samples of every video, so that with two videos,
    the samples of each came out twice, once outside the other's track
    """
    videos = {}
    samples = []
    for name, lat in [("hello", 40.0), ("world", 50.0)]:
        video_path = tmp_path / f"{name}.mp4"
        sample_dir = tmp_path / "samples" / video_path.name
        sample_dir.mkdir(parents=True)
        metadata = _video_metadata(video_path, [float(i) for i in range(10)])
        for p in metadata.points:
            p.lat += lat - 40.0
        videos[name] = metadata
        for k in range(2):
            sample_path = _sample(
                sample_dir, k + 1, START_TIME + datetime.timedelta(seconds=2 * k)
            )
            samples.append(
                sample_path.rename(sample_dir / f"{name}_{sample_path.name}")
            )

    metadatas = GeotagImagesFromVideo(
        list(videos.values()), num_processes=0
    ).to_description(samples)

    lat_by_name = {}
    for metadata in metadatas:
        assert isinstance(metadata, types.ImageMetadata), metadata
        lat_by_name[metadata.filename.name] = metadata.lat
    assert lat_by_name == {
        "hello_hello_v_000001.jpg": pytest.approx(40.0),
        "hello_hello_v_000002.jpg": pytest.approx(40.0002),
        "world_hello_v_000001.jpg": pytest.approx(50.0),
        "world_hello_v_000002.jpg": pytest.approx(50.0002),
    }
    assert len(metadatas) == len(samples)


def test_samples_are_placed_along_a_clock_that_gains(tmp_path: Path):
    """
    Interval samples are stamped along the GPS timestamps of the video. A
    clock that gains on the video, half a second every 4 seconds, is not a
    timelapse, and its track timed by the video placed the samples ahead
    """
    video_path = tmp_path / "hello.mp4"
    sample_dir = tmp_path / "samples" / "hello.mp4"
    sample_dir.mkdir(parents=True)

    gps_seconds = [i + 0.5 * (i // 4) for i in range(10)]
    samples = [
        _sample(
            sample_dir,
            k + 1,
            START_TIME + datetime.timedelta(seconds=gps_seconds[2 * k]),
        )
        for k in range(5)
    ]

    metadatas = GeotagImagesFromVideo(
        [_video_metadata(video_path, gps_seconds)], num_processes=0
    ).to_description(samples)

    lat_by_name = {}
    for metadata in metadatas:
        assert isinstance(metadata, types.ImageMetadata), metadata
        lat_by_name[metadata.filename.name] = metadata.lat
    assert lat_by_name == {
        sample.name: pytest.approx(40.0 + 2 * k * 0.0001)
        for k, sample in enumerate(samples)
    }
