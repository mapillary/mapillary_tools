import json
import os
import subprocess
import tempfile
import typing as T
import zipfile

import exifread
import jsonschema

import py.path
import pytest


EXECUTABLE = os.getenv(
    "MAPILLARY_TOOLS_EXECUTABLE", "python3 -m mapillary_tools.commands"
)
IMPORT_PATH = "tests/data"
USERNAME = "test_username_MAKE_SURE_IT_IS_UNIQUE_AND_LONG_AND_BORING"


@pytest.fixture
def setup_config(tmpdir: py.path.local):
    config_path = tmpdir.mkdir("configs").join("CLIENT_ID")
    os.environ["MAPILLARY_CONFIG_PATH"] = str(config_path)
    x = subprocess.run(
        f"{EXECUTABLE} authenticate --user_name {USERNAME} --jwt test_user_token",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    yield config_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)
    del os.environ["MAPILLARY_CONFIG_PATH"]


@pytest.fixture
def setup_data(tmpdir: py.path.local):
    data_path = tmpdir.mkdir("data")
    source = py.path.local(IMPORT_PATH)
    source.copy(data_path)
    yield data_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


@pytest.fixture
def setup_upload(tmpdir: py.path.local):
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    os.environ["MAPILLARY__DISABLE_BLACKVUE_CHECK"] = "YES"
    os.environ["MAPILLARY__DISABLE_CAMM_CHECK"] = "YES"
    yield upload_dir
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)
    del os.environ["MAPILLARY_UPLOAD_PATH"]
    del os.environ["MAPILLARY__DISABLE_BLACKVUE_CHECK"]


def ffmpeg_installed():
    ffmpeg_path = os.getenv("MAPILLARY_TOOLS_FFMPEG_PATH", "ffmpeg")
    ffprobe_path = os.getenv("MAPILLARY_TOOLS_FFPROBE_PATH", "ffprobe")
    try:
        subprocess.run([ffmpeg_path, "-version"])
        # In Windows, ffmpeg is installed but ffprobe is not?
        subprocess.run([ffprobe_path, "-version"])
    except FileNotFoundError:
        return False
    return True


is_ffmpeg_installed = ffmpeg_installed()


with open("schema/image_description_schema.json") as fp:
    image_description_schema = json.load(fp)


def validate_and_extract_image(image_path: str):
    with open(image_path, "rb") as fp:
        tags = exifread.process_file(fp)
        desc_tag = tags.get("Image ImageDescription")
        assert desc_tag is not None, (tags, image_path)
        desc = json.loads(str(desc_tag.values))
        desc["filename"] = image_path
        desc["filetype"] = "image"
        jsonschema.validate(desc, image_description_schema)
        return desc


def validate_and_extract_zip(filename: str) -> T.List[T.Dict]:
    basename = os.path.basename(filename)
    assert basename.startswith("mly_tools_"), filename
    assert basename.endswith(".zip"), filename
    descs = []

    with zipfile.ZipFile(filename) as zipf:
        with tempfile.TemporaryDirectory() as tempdir:
            zipf.extractall(path=tempdir)
            for name in os.listdir(tempdir):
                desc = validate_and_extract_image(os.path.join(tempdir, name))
                descs.append(desc)

    return descs


def validate_and_extract_camm(filename: str) -> T.List[T.Dict]:
    if not is_ffmpeg_installed:
        return []

    with tempfile.TemporaryDirectory() as tempdir:
        x = subprocess.run(
            f"{EXECUTABLE} --verbose video_process --geotag_source=camm {filename} {tempdir}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr

        # no exif written so we can't extract the image description
        # descs = []
        # for root, _, files in os.walk(tempdir):
        #     for file in files:
        #         if file.endswith(".jpg"):
        #             descs.append(validate_and_extract_image(os.path.join(root, file)))
        # return descs

        # instead, we return the mapillary_image_description.json
        with open(os.path.join(tempdir, "mapillary_image_description.json")) as fp:
            return json.load(fp)
