from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
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
    run_command(
        [
            *["--user_name", USERNAME],
            *["--jwt", "test_user_token"],
        ],
        command="authenticate",
    )
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
            check=True,
        )
        # In Windows, ffmpeg is installed but ffprobe is not?
        subprocess.run(
            [ffprobe_path, "-version"],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            check=True,
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
            check=True,
        )
    except FileNotFoundError:
        return False
    return True


IS_EXIFTOOL_INSTALLED = _exiftool_installed()


def run_exiftool_dir(setup_data: py.path.local) -> py.path.local:
    pytest_skip_if_not_exiftool_installed()

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
    # TODO: Maybe replace with exiftool_runner
    subprocess.run(
        [
            EXIFTOOL_EXECUTABLE,
            "-fast",  # Fast processing
            "-q",  # Quiet mode
            "-r",  # Recursive
            "-n",  # Disable print conversion
            "-X",  # XML output
            "-ee",
            *["-api", "LargeFileSupport=1"],
            *["-w!", str(exiftool_outuput_dir.join("%f%c.xml"))],
            str(setup_data),
        ],
        check=True,
    )
    return exiftool_outuput_dir


def run_exiftool_and_generate_geotag_args(
    test_data_dir: py.path.local, run_args: list[str]
) -> list[str]:
    pytest_skip_if_not_exiftool_installed()

    exiftool_outuput_dir = run_exiftool_dir(test_data_dir)
    return [
        *run_args,
        "--geotag_source=exiftool_xml",
        "--geotag_source_path",
        str(exiftool_outuput_dir),
    ]


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

    return run_process_for_descs(
        ["--file_types=camm", str(video_path)], command="process"
    )


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

    if "MAPGPSTrack" in expected:
        assert expected["MAPGPSTrack"] == actual["MAPGPSTrack"], (
            f"expect {expected['MAPGPSTrack']} but got {actual['MAPGPSTrack']} in {filename}"
        )


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


def assert_descs_exact_equal(left: list[dict], right: list[dict]):
    assert len(left) == len(right)

    # TODO: make sure groups are the same too
    for d in left:
        d.pop("MAPSequenceUUID", None)

    for d in right:
        d.pop("MAPSequenceUUID", None)

    left.sort(key=lambda d: d["filename"])
    right.sort(key=lambda d: d["filename"])

    assert left == right


def run_command(params: list[str], command: str, **kwargs):
    subprocess.run([*shlex.split(EXECUTABLE), command, *params], check=True, **kwargs)


def run_process_for_descs(params: list[str], command: str = "process", **kwargs):
    # Make windows happy with delete=False
    # https://github.com/mapillary/mapillary_tools/issues/503
    if sys.platform in ["win32"]:
        delete = False
    else:
        delete = True
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as desc_file:
        try:
            run_command(
                [
                    "--skip_process_errors",
                    *["--desc_path", str(desc_file.name)],
                    *params,
                ],
                command,
                **kwargs,
            )

            with open(desc_file.name, "r") as fp:
                fp.seek(0)
                descs = json.load(fp)

            if not delete:
                desc_file.close()

        finally:
            if not delete:
                try:
                    os.remove(desc_file.name)
                except FileNotFoundError:
                    pass

    return descs


def run_process_and_upload_for_descs(
    params: list[str], command="process_and_upload", **kwargs
):
    return run_process_for_descs(
        ["--dry_run", *["--user_name", USERNAME], *params], command=command, **kwargs
    )


def run_upload(params: list[str], **kwargs):
    return run_command(
        ["--dry_run", *["--user_name", USERNAME], *params], command="upload", **kwargs
    )


def pytest_skip_if_not_ffmpeg_installed():
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("ffmpeg is not installed, skipping the test")


def pytest_skip_if_not_exiftool_installed():
    if not IS_EXIFTOOL_INSTALLED:
        pytest.skip("exiftool is not installed, skipping the test")


with open("schema/image_description_schema.json") as fp:
    IMAGE_DESCRIPTION_SCHEMA = json.load(fp)
