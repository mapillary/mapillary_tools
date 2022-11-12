import hashlib
import os
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
def test_upload_multiple_mp4s_DEPRECATED(
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    video_path = setup_data.join("videos").join("sample-5s.mp4")
    x = subprocess.run(
        f"{EXECUTABLE} upload_blackvue {UPLOAD_FLAGS} {video_path} {video_path}",
        shell=True,
    )

    assert 1 == len(setup_upload.listdir())
    assert {"mly_tools_8cd0e9af15f4baaafe9dfe98ace8b886.mp4"} == {
        os.path.basename(f) for f in setup_upload.listdir()
    }
    md5sum = file_md5sum(video_path)
    assert {md5sum} == {file_md5sum(f) for f in setup_upload.listdir()}


@pytest.mark.usefixtures("setup_config")
def test_upload_blackvue(
    tmpdir: py.path.local,
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    another_path = tmpdir.join("another_sub")

    video_path2 = another_path.join("sub1 folder").join("sub2 folder").join("hello.mp4")
    video_path2.write_text("hello", encoding="utf-8", ensure=True)

    video_path_invalid_ext = (
        another_path.join("sub1 folder").join("sub2 folder").join("hello.mp45")
    )
    video_path_invalid_ext.write_text("hello2", encoding="utf-8", ensure=True)

    hidden_video_path3 = another_path.join(".subfolder").join("hello.mp4")
    hidden_video_path3.write_text("world", encoding="utf-8", ensure=True)

    video_path_hello2 = tmpdir.join("sub1 folder").join("sub2 folder").join("hello.mp4")
    video_path_hello2.write_text("hello2", encoding="utf-8", ensure=True)

    x = subprocess.run(
        f'{EXECUTABLE} upload_blackvue {UPLOAD_FLAGS} {str(setup_data)} {str(another_path)} "{str(video_path2)}" "{str(video_path_hello2)}"',
        shell=True,
    )
    assert x.returncode == 0, x.stderr

    assert 3 == len(setup_upload.listdir())
    assert {
        "mly_tools_8cd0e9af15f4baaafe9dfe98ace8b886.mp4",
        f"mly_tools_{file_md5sum(str(video_path2))}.mp4",
        f"mly_tools_{file_md5sum(str(video_path_hello2))}.mp4",
    } == {os.path.basename(f) for f in setup_upload.listdir()}


@pytest.mark.usefixtures("setup_config")
def test_upload_camm(
    tmpdir: py.path.local,
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    another_path = tmpdir.join("another_sub")

    video_path2 = another_path.join("sub1 folder").join("sub2 folder").join("hello.mp4")
    video_path2.write_text("hello", encoding="utf-8", ensure=True)

    video_path_invalid_ext = (
        another_path.join("sub1 folder").join("sub2 folder").join("hello.mp45")
    )
    video_path_invalid_ext.write_text("hello2", encoding="utf-8", ensure=True)

    hidden_video_path3 = another_path.join(".subfolder").join("hello.mp4")
    hidden_video_path3.write_text("world", encoding="utf-8", ensure=True)

    video_path_hello2 = tmpdir.join("sub1 folder").join("sub2 folder").join("hello.mp4")
    video_path_hello2.write_text("hello2", encoding="utf-8", ensure=True)

    x = subprocess.run(
        f'{EXECUTABLE} upload_camm {UPLOAD_FLAGS} {str(setup_data)} {str(another_path)} "{str(video_path2)}" "{str(video_path_hello2)}"',
        shell=True,
    )
    assert x.returncode == 0, x.stderr

    assert 3 == len(setup_upload.listdir())
    assert {
        "mly_tools_8cd0e9af15f4baaafe9dfe98ace8b886.mp4",
        f"mly_tools_{file_md5sum(str(video_path2))}.mp4",
        f"mly_tools_{file_md5sum(str(video_path_hello2))}.mp4",
    } == {os.path.basename(f) for f in setup_upload.listdir()}


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
        f"{EXECUTABLE} upload {UPLOAD_FLAGS} --file_types=image {setup_data}",
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
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = setup_data.join("mapillary_image_description.json")

    md5sum_map = {}

    # first upload
    x = subprocess.run(
        f"{EXECUTABLE} upload {UPLOAD_FLAGS} --file_types=image {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for file in setup_upload.listdir():
        validate_and_extract_zip(str(file))
        md5sum_map[os.path.basename(file)] = file_md5sum(file)

    # expect the second upload to not produce new uploads
    x = subprocess.run(
        f"{EXECUTABLE} upload {UPLOAD_FLAGS} --desc_path={desc_path} --file_types=image {setup_data} {setup_data} {setup_data}/images/DSC00001.JPG",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for file in setup_upload.listdir():
        validate_and_extract_zip(str(file))
        new_md5sum = file_md5sum(file)
        assert md5sum_map[os.path.basename(file)] == new_md5sum
    assert len(md5sum_map) == len(setup_upload.listdir())


@pytest.mark.usefixtures("setup_config")
def test_upload_zip(
    tmpdir: py.path.local,
    setup_data: py.path.local,
    setup_upload: py.path.local,
):
    zip_dir = tmpdir.mkdir("zip_dir")
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    x = subprocess.run(
        f"{EXECUTABLE} zip {setup_data} {zip_dir}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for zfile in zip_dir.listdir():
        x = subprocess.run(
            f"{EXECUTABLE} upload_zip {UPLOAD_FLAGS} {zfile} {zfile}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
    for file in setup_upload.listdir():
        validate_and_extract_zip(str(file))
