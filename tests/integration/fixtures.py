import json
import os
import subprocess
import tempfile
import typing as T
import zipfile
from pathlib import Path

import exifread
import jsonschema

import py.path
import pytest


EXECUTABLE = os.getenv(
    "MAPILLARY_TOOLS_EXECUTABLE", "python3 -m mapillary_tools.commands"
)
IMPORT_PATH = "tests/data"
USERNAME = "test_username_MAKE_SURE_IT_IS_UNIQUE_AND_LONG_AND_BORING"


@pytest.fixture
def setup_config(tmpdir: py.path.local):
    config_path = tmpdir.mkdir("configs").join("CLIENT_ID")
    os.environ["MAPILLARY_CONFIG_PATH"] = str(config_path)
    x = subprocess.run(
        f"{EXECUTABLE} authenticate --user_name {USERNAME} --jwt test_user_token",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    yield config_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)
    del os.environ["MAPILLARY_CONFIG_PATH"]


@pytest.fixture
def setup_data(tmpdir: py.path.local):
    data_path = tmpdir.mkdir("data")
    source = py.path.local(IMPORT_PATH)
    source.copy(data_path)
    yield data_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


@pytest.fixture
def setup_upload(tmpdir: py.path.local):
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    os.environ["MAPILLARY__DISABLE_BLACKVUE_CHECK"] = "YES"
    os.environ["MAPILLARY__DISABLE_CAMM_CHECK"] = "YES"
    os.environ["MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN"] = "YES"
    history_path = tmpdir.join("history")
    os.environ["MAPILLARY_UPLOAD_HISTORY_PATH"] = str(history_path)
    yield upload_dir
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)
    del os.environ["MAPILLARY_UPLOAD_PATH"]
    del os.environ["MAPILLARY__DISABLE_BLACKVUE_CHECK"]
    del os.environ["MAPILLARY_UPLOAD_HISTORY_PATH"]
    del os.environ["MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN"]


def ffmpeg_installed():
    ffmpeg_path = os.getenv("MAPILLARY_TOOLS_FFMPEG_PATH", "ffmpeg")
    ffprobe_path = os.getenv("MAPILLARY_TOOLS_FFPROBE_PATH", "ffprobe")
    try:
        subprocess.run(
            [ffmpeg_path, "-version"], stderr=subprocess.PIPE, stdout=subprocess.PIPE
        )
        # In Windows, ffmpeg is installed but ffprobe is not?
        subprocess.run(
            [ffprobe_path, "-version"], stderr=subprocess.PIPE, stdout=subprocess.PIPE
        )
    except FileNotFoundError:
        return False
    return True


is_ffmpeg_installed = ffmpeg_installed()


with open("schema/image_description_schema.json") as fp:
    image_description_schema = json.load(fp)


def validate_and_extract_image(image_path: str):
    with open(image_path, "rb") as fp:
        tags = exifread.process_file(fp)
        desc_tag = tags.get("Image ImageDescription")
        assert desc_tag is not None, (tags, image_path)
        desc = json.loads(str(desc_tag.values))
        desc["filename"] = image_path
        desc["filetype"] = "image"
        jsonschema.validate(desc, image_description_schema)
        return desc


def validate_and_extract_zip(zip_path: str) -> T.List[T.Dict]:
    descs = []

    with zipfile.ZipFile(zip_path) as zipf:
        upload_md5sum = json.loads(zipf.comment)["upload_md5sum"]
        with tempfile.TemporaryDirectory() as tempdir:
            zipf.extractall(path=tempdir)
            for name in os.listdir(tempdir):
                filename = os.path.join(tempdir, name)
                desc = validate_and_extract_image(filename)
                descs.append(desc)

    basename = os.path.basename(zip_path)
    assert f"mly_tools_{upload_md5sum}.zip" == basename, (basename, upload_md5sum)

    return descs


def validate_and_extract_camm(filename: str) -> T.List[T.Dict]:
    if not is_ffmpeg_installed:
        return []

    with tempfile.TemporaryDirectory() as tempdir:
        x = subprocess.run(
            f"{EXECUTABLE} --verbose video_process --video_sample_interval=2 --video_sample_distance=-1 --geotag_source=camm {filename} {tempdir}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr

        # no exif written so we can't extract the image description
        # descs = []
        # for root, _, files in os.walk(tempdir):
        #     for file in files:
        #         if file.endswith(".jpg"):
        #             descs.append(validate_and_extract_image(os.path.join(root, file)))
        # return descs

        # instead, we return the mapillary_image_description.json
        with open(os.path.join(tempdir, "mapillary_image_description.json")) as fp:
            return json.load(fp)


def verify_descs(expected: T.List[T.Dict], actual: T.Union[Path, T.List[T.Dict]]):
    if isinstance(actual, Path):
        with actual.open("r") as fp:
            actual = json.load(fp)
    assert isinstance(actual, list), actual

    expected_map = {desc["filename"]: desc for desc in expected}
    assert len(expected) == len(expected_map), expected

    actual_map = {desc["filename"]: desc for desc in actual}
    assert len(actual) == len(actual_map), actual

    for filename, expected_desc in expected_map.items():
        actual_desc = actual_map.get(filename)
        assert actual_desc is not None, expected_desc
        if "error" in expected_desc:
            assert expected_desc["error"]["type"] == actual_desc["error"]["type"]
            if "message" in expected_desc["error"]:
                assert (
                    expected_desc["error"]["message"] == actual_desc["error"]["message"]
                )
        if "filetype" in expected_desc:
            assert expected_desc["filetype"] == actual_desc.get("filetype"), actual_desc

        if "MAPCompassHeading" in expected_desc:
            e = expected_desc["MAPCompassHeading"]
            assert "MAPCompassHeading" in actual_desc, actual_desc
            a = actual_desc["MAPCompassHeading"]
            assert abs(e["TrueHeading"] - a["TrueHeading"]) < 0.00001
            assert abs(e["MagneticHeading"] - a["MagneticHeading"]) < 0.00001

        if "MAPCaptureTime" in expected_desc:
            assert (
                expected_desc["MAPCaptureTime"] == actual_desc["MAPCaptureTime"]
            ), f'expect {expected_desc["MAPCaptureTime"]} but got {actual_desc["MAPCaptureTime"]} in {filename}'

        if "MAPLongitude" in expected_desc:
            assert (
                abs(expected_desc["MAPLongitude"] - actual_desc["MAPLongitude"])
                < 0.00001
            ), f'expect {expected_desc["MAPLongitude"]} but got {actual_desc["MAPLongitude"]} in {filename}'

        if "MAPLatitude" in expected_desc:
            assert (
                abs(expected_desc["MAPLatitude"] - actual_desc["MAPLatitude"]) < 0.00001
            ), f'expect {expected_desc["MAPLatitude"]} but got {actual_desc["MAPLatitude"]} in {filename}'

        if "MAPAltitude" in expected_desc:
            assert (
                abs(expected_desc["MAPAltitude"] - actual_desc["MAPAltitude"]) < 0.001
            ), f'expect {expected_desc["MAPAltitude"]} but got {actual_desc["MAPAltitude"]} in {filename}'

        if "MAPDeviceMake" in expected_desc:
            assert expected_desc["MAPDeviceMake"] == actual_desc["MAPDeviceMake"]

        if "MAPDeviceModel" in expected_desc:
            assert expected_desc["MAPDeviceModel"] == actual_desc["MAPDeviceModel"]
