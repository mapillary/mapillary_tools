import subprocess

import py.path
import pytest

from .fixtures import EXECUTABLE, setup_config, setup_data, setup_upload, USERNAME

UPLOAD_FLAGS = f"--dry_run --user_name={USERNAME}"


@pytest.mark.usefixtures("setup_config")
def test_upload_images(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    assert len(setup_upload.listdir()) == 0

    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload --file_types=image {UPLOAD_FLAGS} {str(setup_data)}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert 0 < len(setup_upload.listdir()), "should be uploaded for the first time"
    for upload in setup_upload.listdir():
        upload.remove()

    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload --file_types=image {UPLOAD_FLAGS} {str(setup_data)}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert len(setup_upload.listdir()) == 0, (
        "should NOT upload because it is uploaded already"
    )


@pytest.mark.usefixtures("setup_config")
def test_upload_gopro(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    assert len(setup_upload.listdir()) == 0
    video_dir = setup_data.join("gopro_data")

    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload --skip_process_errors {UPLOAD_FLAGS} {str(video_dir)}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert len(setup_upload.listdir()) == 1, (
        f"should be uploaded for the first time but got {setup_upload.listdir()}"
    )
    for upload in setup_upload.listdir():
        upload.remove()
    assert len(setup_upload.listdir()) == 0

    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload --skip_process_errors {UPLOAD_FLAGS} {str(video_dir)}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert len(setup_upload.listdir()) == 0, (
        "should NOT upload because it is uploaded already"
    )
