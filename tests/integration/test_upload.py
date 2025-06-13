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
    validate_uploaded_images,
)


PROCESS_FLAGS = ""
UPLOAD_FLAGS = f"--dry_run --user_name={USERNAME}"


@pytest.mark.usefixtures("setup_config")
def test_upload_image_dir(setup_data: py.path.local, setup_upload: py.path.local):
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data}",
        shell=True,
    )
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
        for desc in descs:
            # TODO: check if the descs are valid
            pass

    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {UPLOAD_FLAGS} --file_types=image {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr

    descs = validate_uploaded_images(Path(setup_upload))
    for x in descs:
        # TODO: check if the descs are valid
        pass


@pytest.mark.usefixtures("setup_config")
def test_upload_image_dir_twice(setup_data: py.path.local, setup_upload: py.path.local):
    x = subprocess.run(
        f"{EXECUTABLE} process --skip_process_errors {PROCESS_FLAGS} {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = setup_data.join("mapillary_image_description.json")

    # first upload
    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {UPLOAD_FLAGS} --file_types=image {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    validate_uploaded_images(Path(setup_upload))

    # expect the second upload to not produce new uploads
    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {UPLOAD_FLAGS} --desc_path={desc_path} --file_types=image {setup_data} {setup_data} {setup_data}/images/DSC00001.JPG",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    validate_uploaded_images(Path(setup_upload))


@pytest.mark.usefixtures("setup_config")
def test_upload_wrong_descs(setup_data: py.path.local, setup_upload: py.path.local):
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
