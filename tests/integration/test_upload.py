import hashlib
import json
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
    validate_and_extract_zip,
)


PROCESS_FLAGS = ""
UPLOAD_FLAGS = f"--dry_run --user_name={USERNAME}"


def file_md5sum(path) -> str:
    with open(path, "rb") as fp:
        md5 = hashlib.md5()
        while True:
            buf = fp.read(1024 * 1024 * 32)
            if not buf:
                break
            md5.update(buf)
        return md5.hexdigest()


@pytest.mark.usefixtures("setup_config")
def test_upload_image_dir(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {UPLOAD_FLAGS} --file_types=image {setup_data}",
        shell=True,
    )
    for file in setup_upload.listdir():
        validate_and_extract_zip(str(file))
    assert x.returncode == 0, x.stderr


@pytest.mark.usefixtures("setup_config")
def test_upload_image_dir_twice(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    x = subprocess.run(
        f"{EXECUTABLE} process --skip_process_errors {PROCESS_FLAGS} {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = setup_data.join("mapillary_image_description.json")

    md5sum_map = {}

    # first upload
    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {UPLOAD_FLAGS} --file_types=image {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for file in setup_upload.listdir():
        validate_and_extract_zip(str(file))
        md5sum_map[os.path.basename(file)] = file_md5sum(file)

    # expect the second upload to not produce new uploads
    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {UPLOAD_FLAGS} --desc_path={desc_path} --file_types=image {setup_data} {setup_data} {setup_data}/images/DSC00001.JPG",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for file in setup_upload.listdir():
        validate_and_extract_zip(str(file))
        new_md5sum = file_md5sum(file)
        assert md5sum_map[os.path.basename(file)] == new_md5sum
    assert len(md5sum_map) == len(setup_upload.listdir())


@pytest.mark.usefixtures("setup_config")
def test_upload_wrong_descs(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    x = subprocess.run(
        f"{EXECUTABLE} process --skip_process_errors {PROCESS_FLAGS} {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path, "r") as fp:
        descs = json.load(fp)
    descs.append(
        {
            "filename": str(setup_data.join("not_found")),
            "filetype": "image",
            "MAPLatitude": 1,
            "MAPLongitude": 1,
            "MAPCaptureTime": "1970_01_01_00_00_02_000",
            "MAPCompassHeading": {"TrueHeading": 17.0, "MagneticHeading": 17.0},
        },
    )
    with open(desc_path, "w") as fp:
        fp.write(json.dumps(descs))

    x = subprocess.run(
        f"{EXECUTABLE} upload {UPLOAD_FLAGS} --desc_path={desc_path} {setup_data} {setup_data} {setup_data}/images/DSC00001.JPG",
        shell=True,
    )
    assert x.returncode == 4, x.stderr
