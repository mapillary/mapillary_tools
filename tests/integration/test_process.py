import json
import os
import subprocess
import zipfile

import pytest
import py.path
import exifread

EXECUTABLE = os.getenv("MAPILLARY_TOOLS_EXECUTABLE", "python3 -m mapillary_tools")
IMPORT_PATH = "tests/integration/mapillary_tools_process_images_provider/data"
USERNAME = "test_username"
CONFIG_CONTENT = f"""
[{USERNAME}]
MAPSettingsUsername = {USERNAME}
MAPSettingsUserKey = test_user_key
user_upload_token = test_user_token
"""


@pytest.fixture
def setup_config(tmpdir: py.path.local):
    config_path = tmpdir.mkdir("configs").join("CLIENT_ID")
    with open(config_path, "w") as fp:
        fp.write(CONFIG_CONTENT)
    yield config_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


@pytest.fixture
def setup_data(tmpdir: py.path.local):
    data_path = tmpdir.mkdir("data")
    source = py.path.local(IMPORT_PATH)
    source.copy(data_path)
    yield data_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


def test_basic():
    for option in ["--version", "--help"]:
        x = subprocess.run(f"{EXECUTABLE} {option}", shell=True)
        assert x.returncode == 0, x.stderr


def test_process(setup_data: py.path.local):
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = os.path.join(setup_data, "mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
    for desc in descs:
        assert "filename" in desc
        assert os.path.isfile(os.path.join(setup_data, desc["filename"]))


def validate_and_extract_zip(filename: str):
    basename = os.path.basename(filename)
    assert basename.startswith("mly_tools_"), filename
    assert basename.endswith(".zip"), filename
    ret = {}
    import tempfile

    with zipfile.ZipFile(filename) as zipf:
        with tempfile.TemporaryDirectory() as tempdir:
            zipf.extractall(path=tempdir)
            for name in os.listdir(tempdir):
                with open(os.path.join(tempdir, name), "rb") as fp:
                    tags = exifread.process_file(fp)
                    desc_tag = tags.get("Image ImageDescription")
                    assert desc_tag is not None, tags
                    desc = json.loads(str(desc_tag.values))
                    assert isinstance(desc.get("MAPLatitude"), (float, int)), desc
                    assert isinstance(desc.get("MAPLongitude"), (float, int)), desc
                    assert isinstance(desc.get("MAPCaptureTime"), str), desc
                    for key in desc.keys():
                        assert key.startswith("MAP"), key
                    ret[name] = desc
    return ret


def test_zip(tmpdir: py.path.local, setup_data: py.path.local):
    zip_dir = tmpdir.mkdir("zip_dir")
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    x = subprocess.run(
        f"{EXECUTABLE} zip {setup_data} {zip_dir}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert 0 < len(zip_dir.listdir())
    for file in zip_dir.listdir():
        validate_and_extract_zip(str(file))


def test_upload_image_dir(
    tmpdir: py.path.local, setup_config: py.path.local, setup_data: py.path.local
):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    x = subprocess.run(
        f"{EXECUTABLE} upload {setup_data} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    for file in upload_dir.listdir():
        validate_and_extract_zip(str(file))
    assert x.returncode == 0, x.stderr


def test_upload_zip(
    tmpdir: py.path.local, setup_data: py.path.local, setup_config: py.path.local
):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    zip_dir = tmpdir.mkdir("zip_dir")
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
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
            f"{EXECUTABLE} upload {zfile} --dry_run --user_name={USERNAME}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
    for file in upload_dir.listdir():
        validate_and_extract_zip(str(file))


def test_process_and_upload(
    tmpdir: py.path.local, setup_config: py.path.local, setup_data: py.path.local
):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {setup_data} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for file in upload_dir.listdir():
        validate_and_extract_zip(str(file))


def test_process_boolean_options(
    setup_config: py.path.local, setup_data: py.path.local
):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    boolean_options = [
        "--add_file_name",
        "--add_import_date",
        "--exclude_import_path",
        "--interpolate_directions",
        "--overwrite_EXIF_direction_tag",
        "--overwrite_EXIF_gps_tag",
        "--overwrite_EXIF_orientation_tag",
        "--overwrite_EXIF_time_tag",
        "--overwrite_all_EXIF_tags",
        "--skip_subfolders",
        "--windows_path",
    ]
    for option in boolean_options:
        x = subprocess.run(
            f"{EXECUTABLE} process {setup_data} {option}",
            shell=True,
        )
        assert x.returncode == 0
    all_options = " ".join(boolean_options)
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} {all_options}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
