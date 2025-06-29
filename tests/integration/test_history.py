import py.path
import pytest

from .fixtures import (
    run_process_and_upload_for_descs,
    setup_config,
    setup_data,
    setup_upload,
)


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
