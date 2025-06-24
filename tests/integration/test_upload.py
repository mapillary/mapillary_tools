import json
import subprocess
from pathlib import Path

import py.path
import pytest

from .fixtures import (
    assert_contains_image_descs,
    EXECUTABLE,
    extract_all_uploaded_descs,
    setup_config,
    setup_data,
    setup_upload,
    USERNAME,
)


PROCESS_FLAGS = ""
UPLOAD_FLAGS = f"--dry_run --user_name={USERNAME}"


@pytest.mark.usefixtures("setup_config")
def test_upload_image_dir(setup_data: py.path.local, setup_upload: py.path.local):
    subprocess.run(
        f"{EXECUTABLE} process {PROCESS_FLAGS} --file_types=image {setup_data}",
        shell=True,
        check=True,
    )

    subprocess.run(
        f"{EXECUTABLE} process_and_upload {UPLOAD_FLAGS} --file_types=image {setup_data}",
        shell=True,
        check=True,
    )

    uploaded_descs: list[dict] = sum(extract_all_uploaded_descs(Path(setup_upload)), [])
    assert len(uploaded_descs) > 0, "No images were uploaded"

    assert_contains_image_descs(
        Path(setup_data.join("mapillary_image_description.json")),
        uploaded_descs,
    )


@pytest.mark.usefixtures("setup_config")
def test_upload_image_dir_twice(setup_data: py.path.local, setup_upload: py.path.local):
    subprocess.run(
        f"{EXECUTABLE} process --skip_process_errors {PROCESS_FLAGS} {setup_data}",
        shell=True,
        check=True,
    )
    desc_path = setup_data.join("mapillary_image_description.json")

    # first upload
    subprocess.run(
        f"{EXECUTABLE} process_and_upload {UPLOAD_FLAGS} --file_types=image {setup_data}",
        shell=True,
        check=True,
    )
    first_descs = extract_all_uploaded_descs(Path(setup_upload))
    assert_contains_image_descs(
        Path(desc_path),
        sum(first_descs, []),
    )

    # expect the second upload to not produce new uploads
    subprocess.run(
        f"{EXECUTABLE} process_and_upload {UPLOAD_FLAGS} --desc_path={desc_path} --file_types=image {setup_data} {setup_data} {setup_data}/images/DSC00001.JPG",
        shell=True,
        check=True,
    )
    second_descs = extract_all_uploaded_descs(Path(setup_upload))
    assert_contains_image_descs(
        Path(desc_path),
        sum(second_descs, []),
    )


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
            "MAPLongitude": 181,
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
    assert x.returncode == 15, x.stderr


@pytest.mark.usefixtures("setup_config")
def test_upload_read_descs_from_stdin(
    setup_data: py.path.local, setup_upload: py.path.local
):
    descs = [
        {
            "filename": "foo.jpg",
            "filetype": "image",
            "MAPLatitude": 1.0,
            "MAPLongitude": 2.0,
            "MAPCaptureTime": "2020_01_02_11_12_13_123456",
        },
    ]
    descs_json = json.dumps(descs)

    process = subprocess.Popen(
        f"{EXECUTABLE} process_and_upload {UPLOAD_FLAGS} --file_types=image {setup_data}",
        stdin=subprocess.PIPE,
        text=True,
        shell=True,
    )

    stdout, stderr = process.communicate(input=descs_json)
    assert process.returncode == 0, stderr

    uploaded_descs: list[dict] = sum(extract_all_uploaded_descs(Path(setup_upload)), [])
    assert len(uploaded_descs) > 0, "No images were uploaded"

    assert_contains_image_descs(
        Path(setup_data.join("mapillary_image_description.json")),
        uploaded_descs,
    )
