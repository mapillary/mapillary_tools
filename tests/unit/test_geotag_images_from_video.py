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


def _video_metadata(video_path: Path, rate: float) -> types.VideoMetadata:
    # One point per second of video, recorded **rate** seconds apart
    points = [
        telemetry.GPSPoint(
            time=float(i),
            lat=40.0 + i * 0.0001,
            lon=-74.0,
            alt=None,
            angle=None,
            epoch_time=START_TIME.timestamp() + rate * i,
            fix=None,
            precision=None,
            ground_speed=None,
        )
        for i in range(10)
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
        [_video_metadata(video_path, rate)], num_processes=0
    ).to_description(samples)

    lat_by_name = {}
    for metadata in metadatas:
        assert isinstance(metadata, types.ImageMetadata), metadata
        lat_by_name[metadata.filename.name] = metadata.lat
    assert lat_by_name == {
        sample.name: pytest.approx(40.0 + 2 * k * 0.0001)
        for k, sample in enumerate(samples)
    }
