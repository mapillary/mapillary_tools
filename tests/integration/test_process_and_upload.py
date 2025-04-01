import datetime
import os
import subprocess

import py.path
import pytest

from .fixtures import (
    EXECUTABLE,
    IS_FFMPEG_INSTALLED,
    setup_config,
    setup_data,
    setup_upload,
    USERNAME,
    validate_and_extract_camm,
    validate_and_extract_zip,
)

PROCESS_FLAGS = ""
UPLOAD_FLAGS = f"--dry_run --user_name={USERNAME}"


EXPECTED_DESCS = {
    "image": {
        "DSC00001.JPG": {
            "MAPAltitude": 70.3,
            "MAPCaptureTime": "2018_06_08_20_24_11_000",
            "MAPCompassHeading": {"MagneticHeading": 270.89, "TrueHeading": 270.89},
            "MAPDeviceMake": "SONY",
            "MAPDeviceModel": "HDR-AS300",
            "MAPLatitude": 45.5169031,
            "MAPLongitude": -122.572765,
            "MAPOrientation": 1,
            "filetype": "image",
        },
        "DSC00497.JPG": {
            "MAPAltitude": 77.5,
            "MAPCaptureTime": "2018_06_08_20_32_28_000",
            "MAPCompassHeading": {"MagneticHeading": 271.27, "TrueHeading": 271.27},
            "MAPDeviceMake": "SONY",
            "MAPDeviceModel": "HDR-AS300",
            "MAPLatitude": 45.5107231,
            "MAPLongitude": -122.5760514,
            "MAPOrientation": 1,
            "filetype": "image",
        },
        "V0370574.JPG": {
            # convert DateTimeOriginal "2018:07:27 11:32:14" in local time to UTC
            "MAPCaptureTime": datetime.datetime.fromisoformat("2018-07-27T11:32:14")
            .astimezone(datetime.timezone.utc)
            .strftime("%Y_%m_%d_%H_%M_%S_%f")[:-3],
            "MAPCompassHeading": {"MagneticHeading": 359.0, "TrueHeading": 359.0},
            "MAPDeviceMake": "Garmin",
            "MAPDeviceModel": "VIRB 360",
            "MAPLatitude": -1.0169444,
            "MAPLongitude": -1.0169444,
            "MAPOrientation": 1,
            "filetype": "image",
        },
    },
    "gopro": {
        "mly_tools_724084a74a44eebd025d0d97a1d5aa30_NA_000001.jpg": {
            "MAPAltitude": -22.18,
            "MAPCaptureTime": "2019_11_18_15_44_47_862",
            "MAPCompassHeading": {"MagneticHeading": 313.689, "TrueHeading": 313.689},
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPLatitude": 33.1266719,
            "MAPLongitude": -117.3273063,
            "MAPOrientation": 1,
            "filetype": "image",
        },
        "mly_tools_724084a74a44eebd025d0d97a1d5aa30_NA_000002.jpg": {
            "MAPAltitude": -21.62,
            "MAPCaptureTime": "2019_11_18_15_44_49_862",
            "MAPCompassHeading": {"MagneticHeading": 326.179, "TrueHeading": 326.179},
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPLatitude": 33.1266891,
            "MAPLongitude": -117.3273151,
            "MAPOrientation": 1,
            "filetype": "image",
        },
        "mly_tools_724084a74a44eebd025d0d97a1d5aa30_NA_000003.jpg": {
            "MAPAltitude": -21.896,
            "MAPCaptureTime": "2019_11_18_15_44_51_862",
            "MAPCompassHeading": {"MagneticHeading": 353.178, "TrueHeading": 353.178},
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPLatitude": 33.1267078,
            "MAPLongitude": -117.3273264,
            "MAPOrientation": 1,
            "filetype": "image",
        },
        "mly_tools_724084a74a44eebd025d0d97a1d5aa30_NA_000004.jpg": {
            "MAPAltitude": -21.997,
            "MAPCaptureTime": "2019_11_18_15_44_53_862",
            "MAPCompassHeading": {"MagneticHeading": 334.427, "TrueHeading": 334.427},
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPLatitude": 33.1267282,
            "MAPLongitude": -117.3273391,
            "MAPOrientation": 1,
            "filetype": "image",
        },
        "mly_tools_724084a74a44eebd025d0d97a1d5aa30_NA_000005.jpg": {
            "MAPAltitude": -22.364,
            "MAPCaptureTime": "2019_11_18_15_44_55_862",
            "MAPCompassHeading": {"MagneticHeading": 325.089, "TrueHeading": 325.089},
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPLatitude": 33.12675,
            "MAPLongitude": -117.3273483,
            "MAPOrientation": 1,
            "filetype": "image",
        },
        "mly_tools_724084a74a44eebd025d0d97a1d5aa30_NA_000006.jpg": {
            "MAPAltitude": -22.539,
            "MAPCaptureTime": "2019_11_18_15_44_57_862",
            "MAPCompassHeading": {"MagneticHeading": 327.867, "TrueHeading": 327.867},
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPLatitude": 33.1267663,
            "MAPLongitude": -117.3273595,
            "MAPOrientation": 1,
            "filetype": "image",
        },
    },
}


def _validate_uploads(upload_dir: py.path.local, expected):
    descs = []
    for file in upload_dir.listdir():
        if str(file).endswith(".mp4"):
            descs.extend(validate_and_extract_camm(str(file)))
        elif str(file).endswith(".zip"):
            descs.extend(validate_and_extract_zip(str(file)))
        else:
            raise Exception(f"invalid file {file}")

    excludes = [
        "filename",
        "filesize",
        "md5sum",
        "MAPMetaTags",
        "MAPSequenceUUID",
        "MAPFilename",
    ]

    actual = {}
    for desc in descs:
        actual[os.path.basename(desc["MAPFilename"])] = {
            k: v for k, v in desc.items() if k not in excludes
        }

    assert expected == actual


@pytest.mark.usefixtures("setup_config")
def test_process_and_upload(setup_data: py.path.local, setup_upload: py.path.local):
    input_paths = [
        setup_data.join("videos"),
        setup_data.join("gopro_data"),
        setup_data.join("gopro_data").join("README"),
        setup_data.join("images"),
        setup_data.join("images"),
        setup_data.join("images").join("DSC00001.JPG"),
    ]
    x = subprocess.run(
        f"{EXECUTABLE} --verbose process_and_upload {UPLOAD_FLAGS} {' '.join(map(str, input_paths))} --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    if IS_FFMPEG_INSTALLED:
        _validate_uploads(
            setup_upload, {**EXPECTED_DESCS["gopro"], **EXPECTED_DESCS["image"]}
        )
    else:
        _validate_uploads(setup_upload, {**EXPECTED_DESCS["image"]})


@pytest.mark.usefixtures("setup_config")
def test_process_and_upload_images_only(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    x = subprocess.run(
        f"""{EXECUTABLE} --verbose process_and_upload \
    {UPLOAD_FLAGS} {PROCESS_FLAGS} \
    --filetypes=image \
    --desc_path=- \
    {setup_data}/images {setup_data}/images {setup_data}/images/DSC00001.JPG
""",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    _validate_uploads(setup_upload, EXPECTED_DESCS["image"])


@pytest.mark.usefixtures("setup_config")
def test_video_process_and_upload(
    setup_upload: py.path.local, setup_data: py.path.local
):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("skip because ffmpeg not installed")

    video_dir = setup_data.join("videos")
    gpx_start_time = "2025_03_14_07_00_00_000"
    gpx_end_time = "2025_03_14_07_01_33_624"
    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")
    x = subprocess.run(
        f"""{EXECUTABLE} video_process_and_upload \
    {PROCESS_FLAGS} {UPLOAD_FLAGS} \
    --video_sample_interval=2 \
    --video_sample_distance=-1 \
    --video_start_time {gpx_start_time} \
    --geotag_source gpx \
    --geotag_source_path {gpx_file} \
    --desc_path - \
    {video_dir} {video_dir.join("my_samples")}
""",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert 1 == len(setup_upload.listdir())
    expected = {
        "sample-5s_NA_000001.jpg": {
            "MAPAltitude": 94.75,
            "MAPCaptureTime": "2025_03_14_07_00_00_000",
            "MAPCompassHeading": {
                "MagneticHeading": 0.484,
                "TrueHeading": 0.484,
            },
            "MAPLatitude": 37.793585,
            "MAPLongitude": -122.461396,
            "MAPOrientation": 1,
            "filetype": "image",
        },
        "sample-5s_NA_000002.jpg": {
            "MAPAltitude": 93.347,
            "MAPCaptureTime": "2025_03_14_07_00_02_000",
            "MAPCompassHeading": {
                "MagneticHeading": 0.484,
                "TrueHeading": 0.484,
            },
            "MAPLatitude": 37.7937349,
            "MAPLongitude": -122.4613944,
            "MAPOrientation": 1,
            "filetype": "image",
        },
        "sample-5s_NA_000003.jpg": {
            "MAPAltitude": 92.492,
            "MAPCaptureTime": "2025_03_14_07_00_04_000",
            "MAPCompassHeading": {
                "MagneticHeading": 343.286,
                "TrueHeading": 343.286,
            },
            "MAPLatitude": 37.7938825,
            "MAPLongitude": -122.4614226,
            "MAPOrientation": 1,
            "filetype": "image",
        },
    }
    _validate_uploads(setup_upload, expected)


@pytest.mark.usefixtures("setup_config")
def test_video_process_and_upload_after_gpx(
    setup_upload: py.path.local, setup_data: py.path.local
):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("skip because ffmpeg not installed")

    video_dir = setup_data.join("videos")
    gpx_start_time = "2025_03_14_07_00_00_000"
    gpx_end_time = "2025_03_14_07_01_33_624"
    video_start_time = "2025_03_14_07_01_34_624"
    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")
    x = subprocess.run(
        f"""{EXECUTABLE} video_process_and_upload \
    {PROCESS_FLAGS} {UPLOAD_FLAGS} \
    --video_sample_interval=2 \
    --video_sample_distance=-1 \
    --video_start_time {video_start_time} \
    --geotag_source gpx \
    --geotag_source_path {gpx_file} \
    --skip_process_errors \
    --desc_path - \
    {video_dir} {video_dir.join("my_samples")}
""",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert 0 == len(setup_upload.listdir())
    _validate_uploads(setup_upload, {})
