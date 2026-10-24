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
from mapillary_tools import exceptions, geo, telemetry, types
from mapillary_tools.exif_write import ExifEdit
from mapillary_tools.geotag import geotag_images_from_video
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


def test_timelapse_samples_are_placed_by_the_gps_clock(tmp_path: Path):
    """
    Samples are stamped by the GPS clock of the video. A GoPro MAX timelapse
    can stamp its first point seconds early, and timed from it, the track
    placed the samples off, and the last ones past its end.
    """
    video_path = tmp_path / "hello.mp4"
    sample_dir = tmp_path / "samples" / "hello.mp4"
    sample_dir.mkdir(parents=True)

    # 10x, but the first timestamp 3 seconds early
    gps_seconds = [0.0] + [3 + 10 * i for i in range(1, 10)]

    video_times = [0.0, 0.5, 2.0, 4.5, 8.0, 9.0]
    samples = [
        _sample(
            sample_dir,
            k + 1,
            START_TIME + datetime.timedelta(seconds=3 + 10 * video_time),
        )
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
    A clock that gains on the video, as a LabPano's runs 8/7 times as fast,
    is no timelapse, and its track timed by the video placed the samples
    ahead. Over more than a minute, as less is too short to measure a pace
    off 1x
    """
    video_path = tmp_path / "hello.mp4"
    sample_dir = tmp_path / "samples" / "hello.mp4"
    sample_dir.mkdir(parents=True)

    gps_seconds = [i * 8 / 7 for i in range(70)]
    samples = [
        _sample(
            sample_dir, k + 1, START_TIME + datetime.timedelta(seconds=2 * k * 8 / 7)
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


def _videos_of_the_same_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[Path, types.VideoMetadata]:
    """
    Two videos named hello.mp4, in the folders x and y, one at 40° north and
    the other at 50°, read as such by the legacy sources
    """
    videos = {}
    for folder, lat in [("x", 40.0), ("y", 50.0)]:
        video_path = tmp_path / "videos" / folder / "hello.mp4"
        video_path.parent.mkdir(parents=True)
        video_path.touch()
        metadata = _video_metadata(video_path, [float(i) for i in range(10)])
        for p in metadata.points:
            p.lat += lat - 40.0
        videos[video_path] = metadata

    class StubGeotagVideos:
        def __init__(self, *args, **kwargs):
            pass

        def to_description(self, video_paths):
            return [videos[video_path] for video_path in video_paths]

    monkeypatch.setattr(
        geotag_images_from_video, "GeotagVideosFromVideo", StubGeotagVideos
    )
    return videos


def test_samples_of_videos_of_the_same_name_are_placed_by_their_own_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    The samples of videos of the same name in different folders were all
    placed along one of them
    """
    _videos_of_the_same_name(tmp_path, monkeypatch)
    samples = []
    for folder in ["x", "y"]:
        # Where sample_video samples videos/x/hello.mp4 from videos/
        sample_dir = tmp_path / "samples" / folder / "hello.mp4"
        sample_dir.mkdir(parents=True)
        samples.extend(
            _sample(sample_dir, k + 1, START_TIME + datetime.timedelta(seconds=2 * k))
            for k in range(2)
        )

    metadatas = geotag_images_from_video.GeotagImageSamplesFromVideo(
        tmp_path / "videos", num_processes=0
    ).to_description(samples)

    lat_by_sample = {}
    for metadata in metadatas:
        assert isinstance(metadata, types.ImageMetadata), metadata
        sample = metadata.filename.relative_to(tmp_path / "samples").as_posix()
        lat_by_sample[sample] = metadata.lat
    assert lat_by_sample == {
        "x/hello.mp4/hello_v_000001.jpg": pytest.approx(40.0),
        "x/hello.mp4/hello_v_000002.jpg": pytest.approx(40.0002),
        "y/hello.mp4/hello_v_000001.jpg": pytest.approx(50.0),
        "y/hello.mp4/hello_v_000002.jpg": pytest.approx(50.0002),
    }


def test_samples_that_could_be_of_several_videos_are_not_placed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    Samples whose folder does not tell which of the videos of the same name
    they are of were placed along one of them
    """
    _videos_of_the_same_name(tmp_path, monkeypatch)
    # Where sample_video samples videos/x/hello.mp4 given alone, or
    # videos/y/hello.mp4
    sample_dir = tmp_path / "samples" / "hello.mp4"
    sample_dir.mkdir(parents=True)
    sample = _sample(sample_dir, 1, START_TIME)

    metadatas = geotag_images_from_video.GeotagImageSamplesFromVideo(
        tmp_path / "videos", num_processes=0
    ).to_description([sample])

    assert len(metadatas) == 1
    assert isinstance(metadatas[0], types.ErrorMetadata)
    assert isinstance(metadatas[0].error, exceptions.MapillaryGeoTaggingError)
    assert str(metadatas[0].error) == (
        "Cannot tell which of the 2 videos named hello.mp4 this is a frame of"
    )


def test_samples_of_videos_of_the_same_name_by_their_exiftool_xml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    The exiftool_xml source finds the samples of the videos whose XML its
    pattern names the same way
    """
    from mapillary_tools.geotag import geotag_images_from_exiftool, options

    videos = _videos_of_the_same_name(tmp_path, monkeypatch)
    for video_path in videos:
        video_path.with_suffix(".xml").touch()

    class StubGeotagVideos:
        def __init__(self, *args, **kwargs):
            pass

        def to_description(self, video_paths):
            return [videos[video_path] for video_path in video_paths]

    monkeypatch.setattr(
        geotag_images_from_exiftool, "GeotagVideosFromExifToolXML", StubGeotagVideos
    )
    samples = []
    for folder in ["x", "y"]:
        sample_dir = tmp_path / "samples" / folder / "hello.mp4"
        sample_dir.mkdir(parents=True)
        samples.append(_sample(sample_dir, 1, START_TIME))
    sample_dir = tmp_path / "samples" / "hello.mp4"
    sample_dir.mkdir(parents=True)
    samples.append(_sample(sample_dir, 1, START_TIME))

    metadatas = geotag_images_from_exiftool.GeotagImagesFromExifToolWithSamples(
        options.SourcePathOption(pattern="%g.xml", source_path=tmp_path / "videos"),
        num_processes=0,
    )._geotag_samples_by_pattern(samples)

    result_by_sample = {
        metadata.filename.relative_to(tmp_path / "samples").as_posix(): (
            str(metadata.error)
            if isinstance(metadata, types.ErrorMetadata)
            else pytest.approx(metadata.lat)
        )
        for metadata in metadatas
    }
    assert result_by_sample == {
        "x/hello.mp4/hello_v_000001.jpg": 40.0,
        "y/hello.mp4/hello_v_000001.jpg": 50.0,
        "hello.mp4/hello_v_000001.jpg": (
            "Cannot tell which of the 2 videos named hello.mp4 this is a frame of"
        ),
    }
