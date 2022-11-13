import json
import subprocess
from pathlib import Path

import py.path
import pytest

from .fixtures import (
    EXECUTABLE,
    setup_config,
    setup_data,
    setup_upload,
    USERNAME,
    validate_and_extract_zip,
)

PROCESS_FLAGS = "--add_import_date"
UPLOAD_FLAGS = f"--dry_run --user_name={USERNAME}"


@pytest.mark.usefixtures("setup_config")
def test_process_and_upload(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload --file_types=image {UPLOAD_FLAGS} {PROCESS_FLAGS} {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert not setup_data.join("mapillary_image_description.json").exists()
    for file in setup_upload.listdir():
        validate_and_extract_zip(str(file))


@pytest.mark.usefixtures("setup_config")
def test_process_and_upload_multiple_import_paths(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    x = subprocess.run(
        f"{EXECUTABLE} --verbose process_and_upload --file_types=image {UPLOAD_FLAGS} {PROCESS_FLAGS} {setup_data} {setup_data}/images/DSC00001.JPG",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for file in setup_upload.listdir():
        validate_and_extract_zip(str(file))


@pytest.mark.usefixtures("setup_config")
def test_process_and_upload_multiple_import_paths_with_desc_path_stdout(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    x = subprocess.run(
        f"{EXECUTABLE} --verbose process_and_upload --file_types=image {UPLOAD_FLAGS} {PROCESS_FLAGS} {setup_data} {setup_data}/images/DSC00001.JPG --desc_path=-",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for file in setup_upload.listdir():
        validate_and_extract_zip(str(file))


@pytest.mark.usefixtures("setup_config")
def test_process_and_upload_multiple_import_paths_with_desc_path_specified(
    tmpdir: py.path.local,
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    desc_path = tmpdir.join("hello.json")
    x = subprocess.run(
        f"{EXECUTABLE} --verbose process_and_upload --file_types=image {UPLOAD_FLAGS} {PROCESS_FLAGS} {setup_data} {setup_data} {setup_data}/images/DSC00001.JPG --desc_path={desc_path}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    with open(desc_path, "r") as fp:
        descs = json.load(fp)

    expected = {
        "DSC00001.JPG": "2018_06_08_13_24_10_000",
        "DSC00497.JPG": "2018_06_08_13_32_28_000",
        "V0370574.JPG": "2018_07_27_11_32_14_000",
    }

    for desc in descs:
        assert "filename" in desc
        assert expected.get(Path(desc["filename"]).name) == desc["MAPCaptureTime"], desc

    for file in setup_upload.listdir():
        validate_and_extract_zip(str(file))
