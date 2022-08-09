import os
import json
import subprocess

import pytest
import py.path

from .test_process import setup_config, setup_upload, EXECUTABLE, is_ffmpeg_installed


IMPORT_PATH = "tests/integration/mapillary_tools_process_images_provider/gopro_data"

expected_descs = [
    {
        "MAPLatitude": 42.0266244,
        "MAPLongitude": -129.2943386,
        "MAPCaptureTime": "2019_11_18_23_42_08_645",
        "MAPAltitude": 9540.24,
        "MAPCompassHeading": {
            "TrueHeading": 123.93587938690177,
            "MagneticHeading": 123.93587938690177,
        },
        "filename": "hero8.mp4/hero8_000001.jpg",
    },
    {
        "MAPLatitude": 38.40647030477047,
        "MAPLongitude": -127.91879935228401,
        "MAPCaptureTime": "2019_11_18_23_42_10_645",
        "MAPAltitude": 8210.638894516123,
        "MAPCompassHeading": {
            "TrueHeading": 164.2783143490891,
            "MagneticHeading": 164.2783143490891,
        },
        "filename": "hero8.mp4/hero8_000002.jpg",
    },
    {
        "MAPLatitude": 35.33045525508525,
        "MAPLongitude": -126.85656645076101,
        "MAPCaptureTime": "2019_11_18_23_42_12_645",
        "MAPAltitude": 7111.61486484729,
        "MAPCompassHeading": {
            "TrueHeading": 140.84083032165609,
            "MagneticHeading": 140.84083032165609,
        },
        "filename": "hero8.mp4/hero8_000003.jpg",
    },
    {
        "MAPLatitude": 35.67994968324376,
        "MAPLongitude": -126.96633932025631,
        "MAPCaptureTime": "2019_11_18_23_42_14_645",
        "MAPAltitude": 7234.620097836571,
        "MAPCompassHeading": {
            "TrueHeading": 139.9975566712228,
            "MagneticHeading": 139.9975566712228,
        },
        "filename": "hero8.mp4/hero8_000004.jpg",
    },
    {
        "MAPLatitude": 36.62692461557483,
        "MAPLongitude": -127.27854373218855,
        "MAPCaptureTime": "2019_11_18_23_42_16_645",
        "MAPAltitude": 7570.467814029364,
        "MAPCompassHeading": {
            "TrueHeading": 137.69409398454923,
            "MagneticHeading": 137.69409398454923,
        },
        "filename": "hero8.mp4/hero8_000005.jpg",
    },
    {
        "MAPLatitude": 36.9141600088776,
        "MAPLongitude": -127.37008598994919,
        "MAPCaptureTime": "2019_11_18_23_42_18_645",
        "MAPAltitude": 7673.03659529988,
        "MAPCompassHeading": {
            "TrueHeading": 344.835906081436,
            "MagneticHeading": 344.835906081436,
        },
        "filename": "hero8.mp4/hero8_000006.jpg",
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


def test_process_gopro_hero8(
    setup_data: py.path.local,
    setup_config: py.path.local,
    setup_upload: py.path.local,
):
    if not is_ffmpeg_installed:
        pytest.skip("skip because ffmpeg not installed")
    video_path = setup_data.join("hero8.mp4")
    x = subprocess.run(
        f"{EXECUTABLE} video_process  --geotag_source=gopro_videos {str(video_path)} --interpolation_use_gpx_start_time",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = setup_data.join("mapillary_sampled_video_frames").join(
        "mapillary_image_description.json"
    )
    assert desc_path.exists()
    with open(desc_path) as fp:
        descs = json.load(fp)
    for expected, actual in zip(expected_descs, descs):
        assert abs(expected["MAPLatitude"] - actual["MAPLatitude"]) < 0.0001
        assert abs(expected["MAPLongitude"] - actual["MAPLongitude"]) < 0.0001
        assert expected["MAPCaptureTime"] == actual["MAPCaptureTime"]
        assert abs(expected["MAPAltitude"] - actual["MAPAltitude"]) < 0.0001
        assert (
            abs(
                expected["MAPCompassHeading"]["TrueHeading"]
                - actual["MAPCompassHeading"]["TrueHeading"]
            )
            < 0.0001
        )
        assert (
            abs(
                expected["MAPCompassHeading"]["MagneticHeading"]
                - actual["MAPCompassHeading"]["MagneticHeading"]
            )
            < 0.0001
        )
        assert expected["filename"] == actual["filename"]
        assert "MAPSequenceUUID" in actual
