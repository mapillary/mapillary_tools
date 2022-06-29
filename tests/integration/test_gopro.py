import os
import json
import subprocess

import py.path

from .test_process import setup_data, setup_config, EXECUTABLE, USERNAME


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


def test_process_blackvue(
    tmpdir: py.path.local, setup_data: py.path.local, setup_config: py.path.local
):
    os.environ["MAPILLARY_CONFIG_PATH"] = str(setup_config)
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
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
        # print(fp.read())
        descs = json.load(fp)
    for expected, actual in zip(expected_descs, descs):
        assert expected["MAPLatitude"] == actual["MAPLatitude"]
        assert expected["MAPLongitude"] == actual["MAPLongitude"]
        assert expected["MAPCaptureTime"] == actual["MAPCaptureTime"]
        assert expected["MAPAltitude"] == actual["MAPAltitude"]
        assert expected["MAPCompassHeading"] == actual["MAPCompassHeading"]
        assert expected["filename"] == actual["filename"]
        assert {
            "strings": [{"key": "mapillary_tools_version", "value": "0.8.2"}]
        } == actual["MAPMetaTags"]
        assert "MAPSequenceUUID" in actual
