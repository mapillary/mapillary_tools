import os
import subprocess

import pytest
import py.path


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
def setup_config(tmpdir):
    config_path = tmpdir.mkdir("configs").join("CLIENT_ID")
    print(f"config path: {config_path}")
    with open(config_path, "w") as fp:
        fp.write(CONFIG_CONTENT)
    yield config_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


@pytest.fixture
def setup_data(tmpdir):
    data_path = tmpdir.mkdir("data")
    print(f"config path: {data_path}")
    source = py.path.local(IMPORT_PATH)
    source.copy(data_path)
    print(f"data dir content: {data_path.listdir()}")
    yield data_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


def test_basic():
    for option in ["--version", "--help"]:
        x = subprocess.run(f"{EXECUTABLE} {option}", shell=True)
        assert x.returncode == 0, x.stderr


def test_process(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr


def test_process_boolean_options(setup_config, setup_data):
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
        "--rerun",
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


def test_process_csv():
    pass


def test_authenticate():
    pass


@pytest.mark.skip(
    "skip because no images in the data directory missing geotags, exiting..."
)
def test_interpolate_missing_gps(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} interpolate --import_path {setup_data} --data missing_gps",
        shell=True,
    )
    assert x.returncode == 0, x.stderr


def xtest_interpolate_identical_timestamps(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} interpolate --import_path {setup_data} --data identical_timestamps",
        shell=True,
    )
    assert x.returncode == 0, x.stderr


def xtest_post_process_boolean_options(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    boolean_options = [
        "--save_as_json",
    ]
    for option in boolean_options:
        x = subprocess.run(
            f"{EXECUTABLE} post_process {setup_data} {option}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
