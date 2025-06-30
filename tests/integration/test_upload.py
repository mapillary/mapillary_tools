import json
import subprocess
from pathlib import Path

import py.path
import pytest

from .fixtures import (
    assert_contains_image_descs,
    extract_all_uploaded_descs,
    run_process_and_upload_for_descs,
    run_process_for_descs,
    run_upload,
    setup_config,
    setup_data,
    setup_upload,
)


@pytest.mark.usefixtures("setup_config")
def test_upload_everything(setup_data: py.path.local, setup_upload: py.path.local):
    descs = run_process_and_upload_for_descs([str(setup_data)])

    uploaded_descs: list[dict] = sum(extract_all_uploaded_descs(Path(setup_upload)), [])
    assert len(uploaded_descs) > 0, "No data were uploaded"
    assert len([d for d in uploaded_descs if d["filetype"] == "camm"]) > 0
    assert len([d for d in uploaded_descs if d["filetype"] == "error"]) == 0
    assert len([d for d in uploaded_descs if d["filetype"] == "image"]) > 0

    # TODO: check video descs
    assert_contains_image_descs(descs, uploaded_descs)


@pytest.mark.usefixtures("setup_config")
def test_upload_image_dir(setup_data: py.path.local, setup_upload: py.path.local):
    descs = run_process_and_upload_for_descs(["--file_types=image", str(setup_data)])

    uploaded_descs: list[dict] = sum(extract_all_uploaded_descs(Path(setup_upload)), [])
    assert len(uploaded_descs) > 0, "No images were uploaded"

    assert_contains_image_descs(descs, uploaded_descs)


@pytest.mark.usefixtures("setup_config")
def test_upload_image_dir_twice(setup_data: py.path.local, setup_upload: py.path.local):
    descs = run_process_for_descs([str(setup_data)])

    # first upload
    first_descs = run_process_and_upload_for_descs(
        ["--file_types=image", str(setup_data)]
    )
    assert len([d for d in first_descs if d["filetype"] == "image"]) > 0
    first_uploaded_descs = extract_all_uploaded_descs(Path(setup_upload))
    assert_contains_image_descs(descs, sum(first_uploaded_descs, []))

    # expect the second upload to not produce new uploads
    second_descs = run_process_and_upload_for_descs(
        [
            "--file_types=image",
            str(setup_data),
            str(setup_data),
            str(setup_data.join("images/DSC00001.JPG")),
        ]
    )
    assert len([d for d in second_descs if d["filetype"] == "image"]) > 0
    second_uploaded_descs = extract_all_uploaded_descs(Path(setup_upload))
    assert_contains_image_descs(descs, sum(second_uploaded_descs, []))


@pytest.mark.usefixtures("setup_config")
def test_upload_wrong_descs(setup_data: py.path.local, setup_upload: py.path.local):
    descs = run_process_for_descs([str(setup_data)])

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

    desc_path = setup_data.join("mapillary_image_description.json")

    with open(desc_path, "w") as fp:
        fp.write(json.dumps(descs))

    with pytest.raises(subprocess.CalledProcessError) as ex:
        run_upload(
            [
                *["--desc_path", str(desc_path)],
                str(setup_data),
                str(setup_data),
                str(setup_data.join("images/DSC00001.JPG")),
            ]
        )

    assert ex.value.returncode == 15, ex.value.stderr
