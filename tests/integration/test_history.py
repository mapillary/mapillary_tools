import os
import subprocess

import pytest
import py.path

from .test_process import EXECUTABLE, USERNAME, setup_data, setup_config, setup_upload


@pytest.fixture
def setup_history_path(tmpdir: py.path.local):
    os.environ["MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN"] = "YES"
    history_path = tmpdir.mkdir("history")
    os.environ["MAPILLARY_UPLOAD_HISTORY_PATH"] = str(history_path)
    yield history_path
    if tmpdir.check():
        history_path.remove(ignore_errors=True)
    os.unsetenv("MAPILLARY_UPLOAD_HISTORY_PATH")
    os.unsetenv("MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN")


def test_upload_images(
    setup_data: py.path.local,
    setup_config: py.path.local,
    setup_history_path: py.path.local,
    setup_upload: py.path.local,
):
    assert len(setup_upload.listdir()) == 0

    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {str(setup_data)} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert 0 < len(setup_upload.listdir()), "should be uploaded for the first time"
    for upload in setup_upload.listdir():
        upload.remove()

    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {str(setup_data)} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert (
        len(setup_upload.listdir()) == 0
    ), "should NOT upload because it is uploaded already"


def test_upload_blackvue(
    setup_data: py.path.local,
    setup_config: py.path.local,
    setup_history_path: py.path.local,
    setup_upload: py.path.local,
):
    assert len(setup_upload.listdir()) == 0

    x = subprocess.run(
        f"{EXECUTABLE} upload_blackvue {str(setup_data)} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert len(setup_upload.listdir()) == 1, "should be uploaded for the first time"
    for upload in setup_upload.listdir():
        upload.remove()
    assert len(setup_upload.listdir()) == 0

    x = subprocess.run(
        f"{EXECUTABLE} upload_blackvue {str(setup_data)} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert (
        len(setup_upload.listdir()) == 0
    ), "should NOT upload because it is uploaded already"
