# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import copy
import functools
import os
import typing as T

import py.path
import pytest

from .fixtures import (
    assert_same_image_descs,
    pytest_skip_if_not_ffmpeg_installed,
    run_exiftool_and_generate_geotag_args,
    run_process_for_descs,
    setup_config,
    setup_upload,
)

run_video_process_for_descs = functools.partial(
    run_process_for_descs, command="video_process"
)

IMPORT_PATH = "tests/data/gopro_data"
TEST_ENVS = {
    "MAPILLARY_TOOLS_GOPRO_GPS_FIXES": "0,2,3",
    "MAPILLARY_TOOLS_GOPRO_MAX_DOP100": "100000",
    "MAPILLARY_TOOLS_GOPRO_GPS_PRECISION": "10000000",
    "MAPILLARY_TOOLS_MAX_CAPTURE_SPEED_KMH": "2000000",  # km/h
}
EXPECTED_DESCS: T.List[T.Any] = [
    {
        "filename": "hero8.mp4/hero8_v_000001.jpg",
        "filetype": "image",
        "MAPAltitude": 9540.24,
        "MAPCaptureTime": "2019_11_18_15_41_12_354",
        "MAPCompassHeading": {
            "TrueHeading": 123.93587938690177,
            "MagneticHeading": 123.93587938690177,
        },
        "MAPLatitude": 42.0266244,
        "MAPLongitude": -129.2943386,
        "MAPDeviceMake": "GoPro",
        "MAPDeviceModel": "HERO8 Black",
        "MAPFilename": "hero8_v_000001.jpg",
    },
    {
        "filename": "hero8.mp4/hero8_v_000002.jpg",
        "filetype": "image",
        "MAPAltitude": 7112.573717404068,
        "MAPCaptureTime": "2019_11_18_15_41_14_354",
        "MAPCompassHeading": {
            "TrueHeading": 140.8665026186285,
            "MagneticHeading": 140.8665026186285,
        },
        "MAPLatitude": 35.33318621742755,
        "MAPLongitude": -126.85929159704702,
        "MAPDeviceMake": "GoPro",
        "MAPDeviceModel": "HERO8 Black",
        "MAPFilename": "hero8_v_000002.jpg",
    },
    {
        "filename": "hero8.mp4/hero8_v_000003.jpg",
        "filetype": "image",
        "MAPAltitude": 7463.642846094319,
        "MAPCaptureTime": "2019_11_18_15_41_16_354",
        "MAPCompassHeading": {
            "TrueHeading": 138.44255851085705,
            "MagneticHeading": 138.44255851085705,
        },
        "MAPLatitude": 36.32681619054138,
        "MAPLongitude": -127.18475264566939,
        "MAPDeviceMake": "GoPro",
        "MAPDeviceModel": "HERO8 Black",
        "MAPFilename": "hero8_v_000003.jpg",
    },
    {
        "filename": "hero8.mp4/hero8_v_000004.jpg",
        "filetype": "image",
        "MAPAltitude": 6909.8168472111465,
        "MAPCaptureTime": "2019_11_18_15_41_18_354",
        "MAPCompassHeading": {
            "TrueHeading": 142.23462669862568,
            "MagneticHeading": 142.23462669862568,
        },
        "MAPLatitude": 34.7537270390268,
        "MAPLongitude": -126.65905680405231,
        "MAPDeviceMake": "GoPro",
        "MAPDeviceModel": "HERO8 Black",
        "MAPFilename": "hero8_v_000004.jpg",
    },
    {
        "filename": "hero8.mp4/hero8_v_000005.jpg",
        "filetype": "image",
        "MAPAltitude": 7212.594480737465,
        "MAPCaptureTime": "2019_11_18_15_41_20_354",
        "MAPCompassHeading": {
            "TrueHeading": 164.70819093235514,
            "MagneticHeading": 164.70819093235514,
        },
        "MAPLatitude": 35.61583820322709,
        "MAPLongitude": -126.93688762007304,
        "MAPDeviceMake": "GoPro",
        "MAPDeviceModel": "HERO8 Black",
        "MAPFilename": "hero8_v_000005.jpg",
    },
    {
        "filename": "hero8.mp4/hero8_v_000006.jpg",
        "filetype": "image",
        "MAPAltitude": 7274.361994963208,
        "MAPCaptureTime": "2019_11_18_15_41_22_354",
        "MAPCompassHeading": {
            "TrueHeading": 139.71549328876722,
            "MagneticHeading": 139.71549328876722,
        },
        "MAPLatitude": 35.79255093264954,
        "MAPLongitude": -126.98833423074615,
        "MAPDeviceMake": "GoPro",
        "MAPDeviceModel": "HERO8 Black",
        "MAPFilename": "hero8_v_000006.jpg",
    },
]


@pytest.fixture
def setup_data(tmpdir: py.path.local):
    data_path = tmpdir.mkdir("data")
    source = py.path.local(IMPORT_PATH)
    source.copy(data_path)
    yield data_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


@pytest.mark.usefixtures("setup_config")
@pytest.mark.usefixtures("setup_upload")
def test_process_gopro_hero8(
    setup_data: py.path.local,
    use_exiftool: bool = False,
):
    pytest_skip_if_not_ffmpeg_installed()

    video_path = setup_data.join("hero8.mp4")

    if use_exiftool:
        args = [
            "--video_sample_interval=2",
            "--video_sample_distance=-1",
            str(video_path),
        ]
        args = run_exiftool_and_generate_geotag_args(setup_data, args)
    else:
        args = [
            "--video_sample_interval=2",
            "--video_sample_distance=-1",
            "--geotag_source=gopro_videos",
            str(video_path),
        ]

    env = os.environ.copy()
    env.update(TEST_ENVS)
    descs = run_video_process_for_descs(args, env=env)
    sample_dir = setup_data.join("mapillary_sampled_video_frames")
    expected_descs = copy.deepcopy(EXPECTED_DESCS)
    for expected_desc in expected_descs:
        expected_desc["filename"] = str(sample_dir.join(expected_desc["filename"]))

    assert_same_image_descs(descs, expected_descs)


@pytest.mark.usefixtures("setup_config")
@pytest.mark.usefixtures("setup_upload")
def test_process_gopro_hero8_with_exiftool(setup_data: py.path.local):
    return test_process_gopro_hero8(setup_data, use_exiftool=True)


@pytest.mark.usefixtures("setup_config")
@pytest.mark.usefixtures("setup_upload")
def test_process_gopro_hero8_with_exiftool_multiple_videos_with_the_same_name(
    setup_data: py.path.local,
):
    video_path = setup_data.join("hero8.mp4")
    for idx in range(11):
        video_dir = setup_data.mkdir(f"video_dir_{idx}")
        video_path.copy(video_dir.join(video_path.basename))
    return test_process_gopro_hero8(setup_data, use_exiftool=True)
