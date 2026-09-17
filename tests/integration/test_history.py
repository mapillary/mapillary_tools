# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import json
import os
from pathlib import Path

import py.path
import pytest

from .fixtures import (
    run_check_upload_history,
    run_process_and_upload_for_descs,
    run_process_for_descs,
    setup_config,
    setup_data,
    setup_upload,
)


@pytest.mark.usefixtures("setup_config")
def test_check_upload_history_is_read_only_and_matches_upload(
    setup_data: py.path.local, setup_upload: py.path.local
):
    process_args = [
        "--cutoff_time",
        "1000",
        "--cutoff_distance",
        "1000",
        str(setup_data),
    ]
    descs = run_process_for_descs(process_args)
    desc_path = setup_data.join("check-upload-history-description.json")
    desc_path.write(json.dumps(descs))
    command_args = [
        str(setup_data),
        "--desc_path",
        str(desc_path),
    ]

    results = run_check_upload_history(command_args)
    assert results
    assert all(not result["already_uploaded"] for result in results)
    assert not Path(os.environ["MAPILLARY_UPLOAD_HISTORY_PATH"]).exists()

    run_process_and_upload_for_descs(process_args)

    results = run_check_upload_history(command_args)
    assert all(result["already_uploaded"] for result in results)
    assert all(
        result["already_uploaded_filenames"] == result["filenames"]
        for result in results
    )

    image_descs_by_sequence = {}
    for desc in descs:
        if desc.get("filetype") == "image" and "error" not in desc:
            image_descs_by_sequence.setdefault(desc["MAPSequenceUUID"], []).append(desc)
    uploaded_sequence = next(
        sequence for sequence in image_descs_by_sequence.values() if 1 < len(sequence)
    )

    # A smaller current sequence has a different sequence checksum, but each
    # image is still identifiable in the stored descriptions of the old upload.
    subset_descs = uploaded_sequence[:1]
    subset_desc_path = setup_data.join("uploaded-subset-description.json")
    subset_desc_path.write(json.dumps(subset_descs))
    subset_results = run_check_upload_history(
        [
            *(desc["filename"] for desc in subset_descs),
            "--desc_path",
            str(subset_desc_path),
        ]
    )
    assert len(subset_results) == 1
    assert subset_results[0]["sequence_md5sum"] not in {
        result["sequence_md5sum"] for result in results
    }
    assert subset_results[0]["already_uploaded_filenames"] == [
        desc["filename"] for desc in subset_descs
    ]
    assert subset_results[0]["already_uploaded"] is True

    new_image_path = Path(str(setup_data)).joinpath("not-uploaded.jpg")
    new_image_path.write_bytes(b"not uploaded")
    new_desc = {
        **subset_descs[0],
        "filename": str(new_image_path),
        "md5sum": None,
        "MAPCaptureTime": "2030_01_01_00_00_00_000",
    }
    mixed_descs = [subset_descs[0], new_desc]
    mixed_desc_path = setup_data.join("mixed-subset-description.json")
    mixed_desc_path.write(json.dumps(mixed_descs))
    mixed_results = run_check_upload_history(
        [
            *(desc["filename"] for desc in mixed_descs),
            "--desc_path",
            str(mixed_desc_path),
        ]
    )
    assert len(mixed_results) == 1
    assert mixed_results[0]["already_uploaded_filenames"] == [
        subset_descs[0]["filename"]
    ]
    assert mixed_results[0]["already_uploaded"] is False


@pytest.mark.usefixtures("setup_config")
def test_upload_everything(setup_data: py.path.local, setup_upload: py.path.local):
    assert len(setup_upload.listdir()) == 0

    run_process_and_upload_for_descs([str(setup_data)])

    assert 0 < len(setup_upload.listdir()), "should be uploaded for the first time"
    for upload in setup_upload.listdir():
        upload.remove()

    run_process_and_upload_for_descs([str(setup_data)])

    assert len(setup_upload.listdir()) == 0, (
        "should NOT upload because it is uploaded already"
    )


@pytest.mark.usefixtures("setup_config")
def test_upload_gopro(setup_data: py.path.local, setup_upload: py.path.local):
    assert len(setup_upload.listdir()) == 0
    video_dir = setup_data.join("gopro_data")

    run_process_and_upload_for_descs([str(video_dir)])
    assert len(setup_upload.listdir()) == 2, (
        f"should be uploaded for the first time but got {setup_upload.listdir()}"
    )
    for upload in setup_upload.listdir():
        if upload.basename != "file_handles":
            upload.remove()
    assert len(setup_upload.listdir()) == 1

    run_process_and_upload_for_descs([str(video_dir)])
    assert len(setup_upload.listdir()) == 1, (
        "should NOT upload because it is uploaded already"
    )
