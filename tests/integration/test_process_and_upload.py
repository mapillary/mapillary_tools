import os
import subprocess

import py.path
import pytest

from .fixtures import (
    EXECUTABLE,
    setup_config,
    setup_data,
    setup_upload,
    USERNAME,
    validate_and_extract_camm,
    validate_and_extract_zip,
)

PROCESS_FLAGS = "--add_import_date"
UPLOAD_FLAGS = f"--dry_run --user_name={USERNAME}"


expected = {
    "image": {
        "abebe4d14eafd4ed7d51a437f7f3dc41.jpg": {
            "MAPAltitude": 77.5,
            "MAPCaptureTime": "2018_06_08_13_32_28_000",
            "MAPCompassHeading": {"MagneticHeading": 271.27, "TrueHeading": 271.27},
            "MAPDeviceMake": "SONY",
            "MAPDeviceModel": "HDR-AS300",
            "MAPFilename": "DSC00497.JPG",
            "MAPLatitude": 45.510723,
            "MAPLongitude": -122.576051,
            "MAPOrientation": 1,
            "filetype": "image",
        },
        "d330ed2b21260c8ddff9e4585e704398.jpg": {
            "MAPAltitude": 70.3,
            "MAPCaptureTime": "2018_06_08_13_24_10_000",
            "MAPCompassHeading": {"MagneticHeading": 270.89, "TrueHeading": 270.89},
            "MAPDeviceMake": "SONY",
            "MAPDeviceModel": "HDR-AS300",
            "MAPFilename": "DSC00001.JPG",
            "MAPLatitude": 45.516903,
            "MAPLongitude": -122.572765,
            "MAPOrientation": 1,
            "filetype": "image",
        },
        "e48c08e5df11c52270ef2568dbf493d6.jpg": {
            "MAPCaptureTime": "2018_07_27_11_32_14_000",
            "MAPCompassHeading": {"MagneticHeading": 359.0, "TrueHeading": 359.0},
            "MAPDeviceMake": "Garmin",
            "MAPDeviceModel": "VIRB 360",
            "MAPFilename": "V0370574.JPG",
            "MAPLatitude": -1.016944,
            "MAPLongitude": -1.016944,
            "MAPOrientation": 1,
            "filetype": "image",
        },
    },
    "gopro": {
        "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000001.jpg": {
            "MAPAltitude": -22.18,
            "MAPCaptureTime": "2019_11_18_15_44_47_862",
            "MAPCompassHeading": {
                "MagneticHeading": 270.000,
                "TrueHeading": 270.000,
            },
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPFilename": "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000001.jpg",
            "MAPLatitude": 33.126672,
            "MAPLongitude": -117.327306,
            "filetype": "image",
        },
        "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000002.jpg": {
            "MAPAltitude": -21.620033,
            "MAPCaptureTime": "2019_11_18_15_44_49_862",
            "MAPCompassHeading": {"MagneticHeading": 0.0, "TrueHeading": 0.0},
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPFilename": "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000002.jpg",
            "MAPLatitude": 33.126689,
            "MAPLongitude": -117.327315,
            "filetype": "image",
        },
        "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000003.jpg": {
            "MAPAltitude": -21.896055,
            "MAPCaptureTime": "2019_11_18_15_44_51_862",
            "MAPCompassHeading": {"MagneticHeading": 0.0, "TrueHeading": 0.0},
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPFilename": "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000003.jpg",
            "MAPLatitude": 33.126708,
            "MAPLongitude": -117.327326,
            "filetype": "image",
        },
        "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000004.jpg": {
            "MAPAltitude": -21.997156,
            "MAPCaptureTime": "2019_11_18_15_44_53_862",
            "MAPCompassHeading": {"MagneticHeading": 0.0, "TrueHeading": 0.0},
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPFilename": "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000004.jpg",
            "MAPLatitude": 33.126728,
            "MAPLongitude": -117.327339,
            "filetype": "image",
        },
        "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000005.jpg": {
            "MAPAltitude": -22.364480,
            "MAPCaptureTime": "2019_11_18_15_44_55_862",
            "MAPCompassHeading": {"MagneticHeading": 0.0, "TrueHeading": 0.0},
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPFilename": "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000005.jpg",
            "MAPLatitude": 33.12675,
            "MAPLongitude": -117.327348,
            "filetype": "image",
        },
        "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000006.jpg": {
            "MAPAltitude": -22.539005,
            "MAPCaptureTime": "2019_11_18_15_44_57_862",
            "MAPCompassHeading": {
                "MagneticHeading": 270.000000,
                "TrueHeading": 270.000000,
            },
            "MAPDeviceMake": "GoPro",
            "MAPDeviceModel": "GoPro Max",
            "MAPFilename": "mly_tools_92af1ea1be0bed02fba868c97b5943cc_000006.jpg",
            "MAPLatitude": 33.126766,
            "MAPLongitude": -117.32736,
            "filetype": "image",
        },
    },
}


def _validate_output(upload_dir: py.path.local, expected):
    descs = []
    for file in upload_dir.listdir():
        if str(file).endswith(".mp4"):
            descs.extend(validate_and_extract_camm(str(file)))
        elif str(file).endswith(".zip"):
            descs.extend(validate_and_extract_zip(str(file)))
        else:
            raise Exception(f"invalid file {file}")
    actual = {}
    for desc in descs:
        actual[os.path.basename(desc["filename"])] = {
            k: v
            for k, v in desc.items()
            if k not in ["filename", "MAPMetaTags", "MAPSequenceUUID"]
        }

    assert expected == actual


@pytest.mark.usefixtures("setup_config")
def test_process_and_upload(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
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
    _validate_output(setup_upload, {**expected["gopro"], **expected["image"]})


@pytest.mark.usefixtures("setup_config")
def test_process_and_upload_images_only(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    x = subprocess.run(
        f"{EXECUTABLE} --verbose process_and_upload --filetypes=image {UPLOAD_FLAGS} {PROCESS_FLAGS} {setup_data} {setup_data} {setup_data}/images/DSC00001.JPG --desc_path=-",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    _validate_output(setup_upload, expected["image"])
