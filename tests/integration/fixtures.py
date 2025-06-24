from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import exifread
import jsonschema

import py.path
import pytest

from mapillary_tools import upload_api_v4, utils

EXECUTABLE = os.getenv(
    "MAPILLARY_TOOLS__TESTS_EXECUTABLE", "python3 -m mapillary_tools.commands"
)
EXIFTOOL_EXECUTABLE = os.getenv(
    "MAPILLARY_TOOLS__TESTS_EXIFTOOL_EXECUTABLE", "exiftool"
)
IMPORT_PATH = "tests/data"
USERNAME = "test_username_MAKE_SURE_IT_IS_UNIQUE_AND_LONG_AND_BORING"


@pytest.fixture
def setup_config(tmpdir: py.path.local):
    config_path = tmpdir.mkdir("configs").join("CLIENT_ID")
    os.environ["MAPILLARY_CONFIG_PATH"] = str(config_path)
    os.environ["MAPILLARY_TOOLS_PROMPT_DISABLED"] = "YES"
    os.environ["MAPILLARY_TOOLS__AUTH_VERIFICATION_DISABLED"] = "YES"
    x = subprocess.run(
        f"{EXECUTABLE} authenticate --user_name {USERNAME} --jwt test_user_token",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    yield config_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)
    os.environ.pop("MAPILLARY_CONFIG_PATH", None)
    os.environ.pop("MAPILLARY_TOOLS_PROMPT_DISABLED", None)
    os.environ.pop("MAPILLARY_TOOLS__AUTH_VERIFICATION_DISABLED", None)


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
    os.environ["MAPILLARY_UPLOAD_ENDPOINT"] = str(upload_dir)
    os.environ["MAPILLARY_TOOLS__AUTH_VERIFICATION_DISABLED"] = "YES"
    os.environ["MAPILLARY_TOOLS_PROMPT_DISABLED"] = "YES"
    os.environ["MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN"] = "YES"
    history_path = tmpdir.join("history")
    os.environ["MAPILLARY_UPLOAD_HISTORY_PATH"] = str(history_path)
    yield upload_dir
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)
    os.environ.pop("MAPILLARY_UPLOAD_ENDPOINT", None)
    os.environ.pop("MAPILLARY_UPLOAD_HISTORY_PATH", None)
    os.environ.pop("MAPILLARY_TOOLS__AUTH_VERIFICATION_DISABLED", None)
    os.environ.pop("MAPILLARY_TOOLS_PROMPT_DISABLED", None)
    os.environ.pop("MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN", None)


def _ffmpeg_installed():
    ffmpeg_path = os.getenv("MAPILLARY_TOOLS_FFMPEG_PATH", "ffmpeg")
    ffprobe_path = os.getenv("MAPILLARY_TOOLS_FFPROBE_PATH", "ffprobe")
    try:
        subprocess.run(
            [ffmpeg_path, "-version"],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        # In Windows, ffmpeg is installed but ffprobe is not?
        subprocess.run(
            [ffprobe_path, "-version"],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
    except FileNotFoundError:
        return False
    return True


IS_FFMPEG_INSTALLED = _ffmpeg_installed()


def _exiftool_installed():
    try:
        subprocess.run(
            [EXIFTOOL_EXECUTABLE, "-ver"],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            shell=True,
        )
    except FileNotFoundError:
        return False
    return True


IS_EXIFTOOL_INSTALLED = _exiftool_installed()


def run_exiftool(setup_data: py.path.local) -> py.path.local:
    exiftool_outuput_dir = setup_data.join("exiftool_outuput_dir")
    # The "-w %c" option in exiftool will produce duplicated XML files therefore clean up the folder first
    shutil.rmtree(exiftool_outuput_dir, ignore_errors=True)

    # Below still causes error in Windows because the XML paths exceeds the max path length (260), hence commented out
    # see https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation

    # if sys.platform in ["win32"]:
    #     # Use %d will create a folder with the drive letter (which causes the creation error in ExifTool)
    #     # Error creating C:/Users/runneradmin/AppData/Local/Temp/test_process_images_with_defau0/data/exiftool_outuput_dir/C:/Users/runneradmin/AppData/Local/Temp/test_process_images_with_defau0/data/videos/sample-5s.xml

    #     # Use %:1d to remove the drive letter:
    #     #                C:/Users/runneradmin/AppData/Local/Temp/test_process_images_with_defau0/data/exiftool_outuput_dir/Users/runneradmin/AppData/Local/Temp/test_process_images_with_defau0/data/videos/sample-5s.xml
    #     subprocess.check_call(
    #         f"{EXIFTOOL_EXECUTABLE} -r -ee -n -X -api LargeFileSupport=1 -w! {exiftool_outuput_dir}/%:1d%f.xml {setup_data}",
    #         shell=True,
    #     )
    # else:
    #     subprocess.check_call(
    #         f"{EXIFTOOL_EXECUTABLE} -r -ee -n -X -api LargeFileSupport=1 -w! {exiftool_outuput_dir}/%d%f.xml {setup_data}",
    #         shell=True,
    #     )

    # The solution is to use %c which suffixes the original filenames with an increasing number
    # -w C%c.txt       # C.txt, C1.txt, C2.txt ...
    # -w C%.c.txt       # C0.txt, C1.txt, C2.txt ...
    subprocess.check_call(
        f"{EXIFTOOL_EXECUTABLE} -r -ee -n -X -api LargeFileSupport=1 -w! {exiftool_outuput_dir}/%f%c.xml {setup_data}",
        shell=True,
    )
    return exiftool_outuput_dir


def run_exiftool_and_generate_geotag_args(
    test_data_dir: py.path.local, run_args: str
) -> str:
    if not IS_EXIFTOOL_INSTALLED:
        pytest.skip("exiftool not installed")
    exiftool_outuput_dir = run_exiftool(test_data_dir)
    exiftool_params = (
        f"--geotag_source exiftool_xml --geotag_source_path {exiftool_outuput_dir}"
    )
    return f"{run_args} {exiftool_params}"


with open("schema/image_description_schema.json") as fp:
    IMAGE_DESCRIPTION_SCHEMA = json.load(fp)


def validate_and_extract_image(image_path: Path):
    with image_path.open("rb") as fp:
        tags = exifread.process_file(fp)

    desc_tag = tags.get("Image ImageDescription")
    assert desc_tag is not None, (tags, image_path)
    desc = json.loads(str(desc_tag.values))
    desc["filename"] = str(image_path)
    desc["filetype"] = "image"
    jsonschema.validate(desc, IMAGE_DESCRIPTION_SCHEMA)
    return desc


def validate_and_extract_zip(zip_path: Path) -> list[dict]:
    with zip_path.open("rb") as fp:
        upload_md5sum = utils.md5sum_fp(fp).hexdigest()

    assert f"mly_tools_{upload_md5sum}.zip" == zip_path.name, (
        zip_path.name,
        upload_md5sum,
    )

    descs = []

    with zipfile.ZipFile(zip_path) as zipf:
        with tempfile.TemporaryDirectory() as tempdir:
            zipf.extractall(path=tempdir)
            for name in os.listdir(tempdir):
                filename = os.path.join(tempdir, name)
                desc = validate_and_extract_image(Path(filename))
                descs.append(desc)

    return descs


def validate_and_extract_camm(video_path: Path) -> list[dict]:
    with video_path.open("rb") as fp:
        upload_md5sum = utils.md5sum_fp(fp).hexdigest()

    assert f"mly_tools_{upload_md5sum}.mp4" == video_path.name, (
        video_path.name,
        upload_md5sum,
    )

    if not IS_FFMPEG_INSTALLED:
        return []

    with tempfile.TemporaryDirectory() as tempdir:
        x = subprocess.run(
            f"{EXECUTABLE} --verbose video_process --video_sample_interval=2 --video_sample_distance=-1 --geotag_source=camm {str(video_path)} {tempdir}",
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


def load_descs(descs) -> list:
    if isinstance(descs, Path):
        with descs.open("r") as fp:
            descs = json.load(fp)
    assert isinstance(descs, list), f"expect a list of descs but got: {descs}"
    return descs


def extract_all_uploaded_descs(upload_folder: Path) -> list[list[dict]]:
    session_by_file_handle: dict[str, str] = {}
    if upload_folder.joinpath(upload_api_v4.FakeUploadService.FILE_HANDLE_DIR).exists():
        for session_path in upload_folder.joinpath(
            upload_api_v4.FakeUploadService.FILE_HANDLE_DIR
        ).iterdir():
            file_handle = session_path.read_text()
            session_by_file_handle[file_handle] = session_path.name

    sequences = []

    for file in upload_folder.iterdir():
        if file.suffix == ".json":
            with file.open() as fp:
                manifest = json.load(fp)
            image_file_handles = manifest["image_handles"]
            assert len(image_file_handles) > 0, manifest
            image_sequence = []
            for file_handle in image_file_handles:
                image_path = upload_folder.joinpath(session_by_file_handle[file_handle])
                with image_path.open("rb") as fp:
                    upload_md5sum = utils.md5sum_fp(fp).hexdigest()
                assert upload_md5sum in image_path.stem, (upload_md5sum, image_path)
                image_sequence.append(validate_and_extract_image(image_path))
            sequences.append(image_sequence)
        elif file.suffix == ".zip":
            sequences.append(validate_and_extract_zip(file))
        elif file.suffix == ".mp4":
            sequences.append(validate_and_extract_camm(file))
        elif file.name == upload_api_v4.FakeUploadService.FILE_HANDLE_DIR:
            # Already processed above
            pass

    return sequences


def approximate(left: float, right: float, threshold=0.00001):
    return abs(left - right) < threshold


def assert_compare_image_descs(expected: dict, actual: dict):
    jsonschema.validate(expected, IMAGE_DESCRIPTION_SCHEMA)
    jsonschema.validate(actual, IMAGE_DESCRIPTION_SCHEMA)

    assert expected.get("MAPFilename"), expected
    assert actual.get("MAPFilename"), actual
    assert expected.get("MAPFilename") == actual.get("MAPFilename")

    filename = actual.get("MAPFilename")

    if "error" in expected:
        assert expected["error"]["type"] == actual.get("error", {}).get("type"), (
            f"{expected=} != {actual=}"
        )
        if "message" in expected["error"]:
            assert expected["error"]["message"] == actual["error"]["message"]

    if "filetype" in expected:
        assert expected["filetype"] == actual.get("filetype"), actual

    if "MAPCompassHeading" in expected:
        e = expected["MAPCompassHeading"]
        assert "MAPCompassHeading" in actual, actual
        a = actual["MAPCompassHeading"]
        assert approximate(e["TrueHeading"], a["TrueHeading"], 0.001), (
            f"got {a['TrueHeading']} but expect {e['TrueHeading']} in {filename}"
        )
        assert approximate(e["MagneticHeading"], a["MagneticHeading"], 0.001), (
            f"got {a['MagneticHeading']} but expect {e['MagneticHeading']} in {filename}"
        )

    if "MAPCaptureTime" in expected:
        assert expected["MAPCaptureTime"] == actual["MAPCaptureTime"], (
            f"expect {expected['MAPCaptureTime']} but got {actual['MAPCaptureTime']} in {filename}"
        )

    if "MAPLongitude" in expected:
        assert approximate(expected["MAPLongitude"], actual["MAPLongitude"], 0.00001), (
            f"expect {expected['MAPLongitude']} but got {actual['MAPLongitude']} in {filename}"
        )

    if "MAPLatitude" in expected:
        assert approximate(expected["MAPLatitude"], actual["MAPLatitude"], 0.00001), (
            f"expect {expected['MAPLatitude']} but got {actual['MAPLatitude']} in {filename}"
        )

    if "MAPAltitude" in expected:
        assert approximate(expected["MAPAltitude"], actual["MAPAltitude"], 0.001), (
            f"expect {expected['MAPAltitude']} but got {actual['MAPAltitude']} in {filename}"
        )

    if "MAPDeviceMake" in expected:
        assert expected["MAPDeviceMake"] == actual["MAPDeviceMake"]

    if "MAPDeviceModel" in expected:
        assert expected["MAPDeviceModel"] == actual["MAPDeviceModel"]


def assert_contains_image_descs(haystack: Path | list[dict], needle: Path | list[dict]):
    """
    Check if the haystack contains all the descriptions in needle.
    """

    haystack = load_descs(haystack)
    needle = load_descs(needle)

    haystack_by_filename = {
        desc["MAPFilename"]: desc for desc in haystack if "MAPFilename" in desc
    }

    needle_by_filename = {
        desc["MAPFilename"]: desc for desc in needle if "MAPFilename" in desc
    }

    assert haystack_by_filename.keys() >= needle_by_filename.keys(), (
        f"haystack {list(haystack_by_filename.keys())} does not contain all the keys in needle {list(needle_by_filename.keys())}"
    )
    for filename, desc in needle_by_filename.items():
        assert_compare_image_descs(desc, haystack_by_filename[filename])


def assert_same_image_descs(left: Path | list[dict], right: Path | list[dict]):
    assert_contains_image_descs(left, right)
    assert_contains_image_descs(right, left)
