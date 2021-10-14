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
    os.environ["MAPILLARY_CONFIG_PATH"] = str(setup_config)
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
    os.environ["MAPILLARY_CONFIG_PATH"] = str(setup_config)
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
    os.environ["MAPILLARY_CONFIG_PATH"] = str(setup_config)
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {setup_data} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for file in upload_dir.listdir():
        validate_and_extract_zip(str(file))


def test_time(setup_data: py.path.local):
    # before offset
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)

    expected = {
        "DSC00001.JPG": "2018_06_08_13_24_10_000",
        "DSC00497.JPG": "2018_06_08_13_32_28_000",
        "V0370574.JPG": "2018_07_27_11_32_14_000",
    }

    for desc in descs:
        assert "filename" in desc
        assert expected[desc["filename"]] == desc["MAPCaptureTime"]

    # after offset
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} --offset_time=2.5",
        shell=True,
    )
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)

    expected = {
        "DSC00001.JPG": "2018_06_08_13_24_12_500",
        "DSC00497.JPG": "2018_06_08_13_32_30_500",
        "V0370574.JPG": "2018_07_27_11_32_16_500",
    }

    for desc in descs:
        assert "filename" in desc
        assert expected[desc["filename"]] == desc["MAPCaptureTime"]

    # after offset
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} --offset_time=-1.0",
        shell=True,
    )
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)

    expected = {
        "DSC00001.JPG": "2018_06_08_13_24_09_000",
        "DSC00497.JPG": "2018_06_08_13_32_27_000",
        "V0370574.JPG": "2018_07_27_11_32_13_000",
    }

    for desc in descs:
        assert "filename" in desc
        assert expected[desc["filename"]] == desc["MAPCaptureTime"]


def test_angle(setup_data: py.path.local):
    # before offset
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
    expected = {
        "DSC00001.JPG": 270.89,
        "DSC00497.JPG": 271.27,
        "V0370574.JPG": 359.0,
    }
    for desc in descs:
        assert "filename" in desc
        assert (
            abs(expected[desc["filename"]] - desc["MAPCompassHeading"]["TrueHeading"])
            < 0.00001
        )
        assert (
            abs(
                expected[desc["filename"]]
                - desc["MAPCompassHeading"]["MagneticHeading"]
            )
            < 0.00001
        )

    # after offset
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} --offset_angle=2.5",
        shell=True,
    )
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
    expected = {
        "DSC00001.JPG": 270.89 + 2.5,
        "DSC00497.JPG": 271.27 + 2.5,
        "V0370574.JPG": 1.5,
    }
    for desc in descs:
        assert "filename" in desc
        assert (
            abs(expected[desc["filename"]] - desc["MAPCompassHeading"]["TrueHeading"])
            < 0.00001
        )
        assert (
            abs(
                expected[desc["filename"]]
                - desc["MAPCompassHeading"]["MagneticHeading"]
            )
            < 0.00001
        )


def test_process_boolean_options(
    setup_config: py.path.local, setup_data: py.path.local
):
    os.environ["MAPILLARY_CONFIG_PATH"] = str(setup_config)
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
