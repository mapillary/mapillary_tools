import os
import subprocess

import pytest
import py.path

from .test_process import EXECUTABLE, USERNAME, setup_data, setup_config


@pytest.fixture
def setup_history_path(tmpdir: py.path.local):
    os.environ["MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN"] = "YES"
    history_path = tmpdir.mkdir("history")
    os.environ["MAPILLARY_UPLOAD_HISTORY_PATH"] = str(history_path)
    yield history_path
    if tmpdir.check():
        history_path.remove(ignore_errors=True)


def test_upload_images(
    tmpdir: py.path.local,
    setup_data: py.path.local,
    setup_config: py.path.local,
    setup_history_path: py.path.local,
):
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    assert len(upload_dir.listdir()) == 0

    os.environ["MAPILLARY__DISABLE_BLACKVUE_CHECK"] = "YES"
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)

    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {str(setup_data)} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert 0 < len(upload_dir.listdir()), "should be uploaded for the first time"
    for upload in upload_dir.listdir():
        upload.remove()

    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {str(setup_data)} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert (
        len(upload_dir.listdir()) == 0
    ), "should NOT upload because it is uploaded already"


def test_upload_blackvue(
    tmpdir: py.path.local,
    setup_data: py.path.local,
    setup_config: py.path.local,
    setup_history_path: py.path.local,
):
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    assert len(upload_dir.listdir()) == 0

    os.environ["MAPILLARY__DISABLE_BLACKVUE_CHECK"] = "YES"
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    x = subprocess.run(
        f"{EXECUTABLE} upload_blackvue {str(setup_data)} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert len(upload_dir.listdir()) == 1, "should be uploaded for the first time"
    for upload in upload_dir.listdir():
        upload.remove()
    assert len(upload_dir.listdir()) == 0
    os.environ["MAPILLARY_UPLOAD_HISTORY_PATH"]

    x = subprocess.run(
        f"{EXECUTABLE} upload_blackvue {str(setup_data)} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert (
        len(upload_dir.listdir()) == 0
    ), "should NOT upload because it is uploaded already"
