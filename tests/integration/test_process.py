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
    for option in ["--version", "--help", "--full_help"]:
        x = subprocess.run(f"{EXECUTABLE} {option}", shell=True)
        assert x.returncode == 0


def test_process(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} process --import_path {setup_data} --user_name {USERNAME}",
        shell=True,
    )
    assert x.returncode == 0


def test_process_boolean_options(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    boolean_options = [
        "--add_file_name",
        "--add_import_date",
        "--exclude_import_path",
        "--interpolate_directions",
        "--keep_duplicates",
        "--keep_original",
        "--list_file_status",
        "--local_time",
        "--move_all_images",
        "--move_duplicates",
        "--move_sequences",
        "--move_uploaded",
        "--overwrite_EXIF_direction_tag",
        "--overwrite_EXIF_gps_tag",
        "--overwrite_EXIF_orientation_tag",
        "--overwrite_EXIF_time_tag",
        "--overwrite_all_EXIF_tags",
        # --private only works with organizations
        # '--private',
        # FIXME: AttributeError: module 'mapillary_tools.uploader' has no attribute 'process_upload_finalization'
        # '--push_images',
        "--rerun",
        "--save_as_json",
        # '--save_local_mapping',
        "--skip_EXIF_insert",
        "--skip_subfolders",
        "--summarize",
        "--use_gps_start_time",
        "--verbose",
        "--windows_path",
    ]
    for option in boolean_options:
        x = subprocess.run(
            f"{EXECUTABLE} --advanced process --import_path {setup_data} --user_name {USERNAME} {option}",
            shell=True,
        )
        assert x.returncode == 0
    all_options = " ".join(boolean_options)
    x = subprocess.run(
        f"{EXECUTABLE} --advanced process --import_path {setup_data} --user_name {USERNAME} {all_options}",
        shell=True,
    )
    assert x.returncode == 0


def test_extract_user_data(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} --advanced extract_user_data --import_path {setup_data} --user_name {USERNAME}",
        shell=True,
    )
    assert x.returncode == 0


def test_extract_geotag_data(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} --advanced extract_geotag_data --import_path {setup_data}",
        shell=True,
    )
    assert x.returncode == 0


def test_extract_import_meta_data(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} --advanced extract_import_meta_data --import_path {setup_data}",
        shell=True,
    )
    assert x.returncode == 0


def test_extract_sequence_data(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} --advanced extract_sequence_data --import_path {setup_data}",
        shell=True,
    )
    assert x.returncode == 0


def test_extract_upload_params(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} --advanced extract_upload_params --import_path {setup_data} --user_name {USERNAME}",
        shell=True,
    )
    assert x.returncode == 0


def test_exif_insert(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} --advanced exif_insert --import_path {setup_data}", shell=True
    )
    assert x.returncode == 0


def test_process_csv():
    pass


def test_authenticate():
    pass


@pytest.mark.skip("skip because no images in the data directory missing geotags, exiting...")
def test_interpolate_missing_gps(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} --advanced interpolate --import_path {setup_data} --data missing_gps",
        shell=True,
    )
    assert x.returncode == 0


def test_interpolate_identical_timestamps(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    x = subprocess.run(
        f"{EXECUTABLE} --advanced interpolate --import_path {setup_data} --data identical_timestamps",
        shell=True,
    )
    assert x.returncode == 0


def test_post_process_boolean_options(setup_config, setup_data):
    os.environ["GLOBAL_CONFIG_FILEPATH"] = str(setup_config)
    boolean_options = [
        "--list_file_status",
        "--move_all_images",
        "--move_duplicates",
        "--move_sequences",
        "--move_uploaded",
        # "--push_images",
        "--save_as_json",
        "--save_local_mapping",
        "--skip_subfolders",
        "--summarize",
    ]
    for option in boolean_options:
        x = subprocess.run(
            f"{EXECUTABLE} --advanced post_process --import_path {setup_data} {option}",
            shell=True,
        )
        assert x.returncode == 0, x.returncode


def test_download():
    pass


def test_send_videos_for_processing():
    pass
