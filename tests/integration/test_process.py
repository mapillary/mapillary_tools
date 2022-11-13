import json
import os
import subprocess
import tempfile
from pathlib import Path

import exifread
import py.path
import pytest

from .fixtures import (
    EXECUTABLE,
    is_ffmpeg_installed,
    setup_config,
    setup_data,
    setup_upload,
    USERNAME,
    validate_and_extract_zip,
)


PROCESS_FLAGS = "--add_import_date"


def test_basic():
    for option in ["--version", "--help"]:
        x = subprocess.run(f"{EXECUTABLE} {option}", shell=True)
        assert x.returncode == 0, x.stderr


def test_process(setup_data: py.path.local):
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = os.path.join(setup_data, "mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
    for desc in descs:
        assert "filename" in desc
        assert os.path.isfile(os.path.join(setup_data, desc["filename"]))


def test_zip(tmpdir: py.path.local, setup_data: py.path.local):
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
    assert 0 < len(zip_dir.listdir())
    for file in zip_dir.listdir():
        validate_and_extract_zip(str(file))


def test_time(setup_data: py.path.local):
    # before offset
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data}",
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
        assert expected.get(Path(desc["filename"]).name) == desc["MAPCaptureTime"], desc

    # after offset
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --offset_time=2.5",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
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
        assert expected.get(Path(desc["filename"]).name) == desc["MAPCaptureTime"]

    # after offset
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --offset_time=-1.0",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
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
        assert expected.get(Path(desc["filename"]).name) == desc["MAPCaptureTime"]


def test_angle(setup_data: py.path.local):
    # before offset
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
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
        assert Path(desc["filename"]).is_file(), desc
        basename = Path(desc["filename"]).name
        assert (
            abs(expected[basename] - desc["MAPCompassHeading"]["TrueHeading"]) < 0.00001
        )
        assert (
            abs(expected[basename] - desc["MAPCompassHeading"]["MagneticHeading"])
            < 0.00001
        )

    # after offset
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --offset_angle=2.5",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
    expected = {
        "DSC00001.JPG": 270.89 + 2.5,
        "DSC00497.JPG": 271.27 + 2.5,
        "V0370574.JPG": 1.5,
    }
    for desc in descs:
        assert "filename" in desc, desc
        assert Path(desc["filename"]).is_file(), desc
        basename = Path(desc["filename"]).name
        assert (
            abs(expected[basename] - desc["MAPCompassHeading"]["TrueHeading"]) < 0.00001
        )
        assert (
            abs(expected[basename] - desc["MAPCompassHeading"]["MagneticHeading"])
            < 0.00001
        )


@pytest.mark.usefixtures("setup_config")
def test_process_boolean_options(setup_data: py.path.local):
    boolean_options = [
        "--add_file_name",
        "--add_import_date",
        "--interpolate_directions",
        "--overwrite_EXIF_direction_tag",
        "--overwrite_EXIF_gps_tag",
        "--overwrite_EXIF_orientation_tag",
        "--overwrite_EXIF_time_tag",
        "--overwrite_all_EXIF_tags",
        "--skip_subfolders",
    ]
    for option in boolean_options:
        x = subprocess.run(
            f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {option} {setup_data}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
    all_options = " ".join(boolean_options)
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {all_options} {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr


GPX_CONTENT = """
    <gpx>
    <trk>
        <name>Mapillary GPX</name>
        <trkseg>
            <trkpt lat="0.02" lon="0.01">
            <ele>1</ele>
            <time>2018-06-08T13:23:34.805</time>
            </trkpt>

            <trkpt lat="2.02" lon="0.01">
            <ele>2</ele>
            <time>2018-06-08T13:24:35.809</time>
            </trkpt>

            <trkpt lat="2.02" lon="2.01">
            <ele>4</ele>
            <time>2018-06-08T13:33:36.813</time>
            </trkpt>

            <trkpt lat="4.02" lon="2.01">
            <ele>9</ele>
            <time>2018-06-08T13:58:37.812</time>
            </trkpt>
        </trkseg>
    </trk>
    </gpx>
"""


def find_desc_errors(descs):
    return [desc for desc in descs if "error" in desc]


def filter_out_errors(descs):
    return [desc for desc in descs if "error" not in desc]


def test_geotagging_from_gpx(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    desc_path = setup_data.join("mapillary_image_description.json")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --geotag_source gpx --geotag_source_path {gpx_file} --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    expected_lonlat = {
        # capture_time, lon, lat, elevation
        "DSC00001.JPG": [
            "2018_06_08_13_24_10_000",
            0.01,
            1.1738587633597797,
            1.5769293816798897,
        ],
        "DSC00497.JPG": [
            "2018_06_08_13_32_28_000",
            1.7556100139740183,
            2.02,
            3.7456100139740185,
        ],
    }

    with open(desc_path) as fp:
        descs = json.load(fp)

    assert {"V0370574.JPG"} == {
        Path(d["filename"]).name for d in find_desc_errors(descs)
    }

    for desc in find_desc_errors(descs):
        assert desc.get("error").get("type") == "MapillaryOutsideGPXTrackError"

    for desc in filter_out_errors(descs):
        assert Path(desc["filename"]).is_file(), desc
        basename = Path(desc["filename"]).name
        assert expected_lonlat.get(basename, [])[0] == desc["MAPCaptureTime"]
        assert (
            abs(expected_lonlat.get(basename, [])[1] - desc["MAPLongitude"]) < 0.00001
        )
        assert abs(expected_lonlat[basename][2] - desc["MAPLatitude"]) < 0.00001
        assert abs(expected_lonlat[basename][3] - desc["MAPAltitude"]) < 0.00001


def test_geotagging_from_gpx_with_offset(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    desc_path = setup_data.join("mapillary_image_description.json")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --geotag_source gpx --geotag_source_path {gpx_file} --interpolation_offset_time=-20 --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr

    expected_lonlat = {
        # capture_time, lon, lat, elevation
        "DSC00001.JPG": [
            "2018_06_08_13_23_50_000",
            0.01,
            0.5181640548160776,
            1.2490820274080388,
        ],
        "DSC00497.JPG": [
            "2018_06_08_13_32_08_000",
            1.6816734072206487,
            2.02,
            3.671673407220649,
        ],
    }

    with open(desc_path) as fp:
        descs = json.load(fp)

    assert {"V0370574.JPG"} == {
        Path(d["filename"]).name for d in find_desc_errors(descs)
    }

    for desc in find_desc_errors(descs):
        assert desc.get("error").get("type") == "MapillaryOutsideGPXTrackError"

    for desc in filter_out_errors(descs):
        basename = Path(desc["filename"]).name
        assert expected_lonlat[basename][0] == desc["MAPCaptureTime"]
        assert abs(expected_lonlat[basename][1] - desc["MAPLongitude"]) < 0.00001
        assert abs(expected_lonlat[basename][2] - desc["MAPLatitude"]) < 0.00001
        assert abs(expected_lonlat[basename][3] - desc["MAPAltitude"]) < 0.00001


def test_geotagging_from_gpx_use_gpx_start_time(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --geotag_source gpx --interpolation_use_gpx_start_time --geotag_source_path {gpx_file} --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    expected_lonlat = {
        # capture_time, lon, lat, elevation
        "DSC00001.JPG": ["2018_06_08_13_23_34_805", 0.01, 0.02, 1.0],
        "DSC00497.JPG": [
            "2018_06_08_13_31_52_805",
            1.6255000702397762,
            2.02,
            3.6155000702397766,
        ],
    }
    desc_path = setup_data.join("mapillary_image_description.json")

    with open(desc_path) as fp:
        descs = json.load(fp)

    assert {"V0370574.JPG"} == {
        Path(d["filename"]).name for d in find_desc_errors(descs)
    }

    for desc in find_desc_errors(descs):
        assert desc.get("error").get("type") == "MapillaryOutsideGPXTrackError"

    for desc in filter_out_errors(descs):
        basename = Path(desc["filename"]).name
        assert Path(desc["filename"]).is_file(), desc
        assert expected_lonlat[basename][0] == desc["MAPCaptureTime"]
        assert abs(expected_lonlat[basename][1] - desc["MAPLongitude"]) < 0.00001
        assert abs(expected_lonlat[basename][2] - desc["MAPLatitude"]) < 0.00001
        assert abs(expected_lonlat[basename][3] - desc["MAPAltitude"]) < 0.00001


def test_geotagging_from_gpx_use_gpx_start_time_with_offset(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --geotag_source gpx --interpolation_use_gpx_start_time --geotag_source_path {gpx_file} --interpolation_offset_time=100 --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    expected_lonlat = {
        # capture_time, lon, lat, elevation
        "DSC00001.JPG": [
            "2018_06_08_13_25_14_805",
            0.15416159584772016,
            2.02,
            2.14416159584772,
        ],
        "DSC00497.JPG": [
            "2018_06_08_13_33_32_805",
            1.9951831040066244,
            2.02,
            3.985183104006625,
        ],
    }
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
    assert {"V0370574.JPG"} == {
        Path(d["filename"]).name for d in find_desc_errors(descs)
    }
    for desc in find_desc_errors(descs):
        assert desc.get("error").get("type") == "MapillaryOutsideGPXTrackError"
    for desc in filter_out_errors(descs):
        assert Path(desc["filename"]).is_file(), desc
        basename = Path(desc["filename"]).name
        assert expected_lonlat[basename][0] == desc["MAPCaptureTime"]
        assert abs(expected_lonlat[basename][1] - desc["MAPLongitude"]) < 0.00001
        assert abs(expected_lonlat[basename][2] - desc["MAPLatitude"]) < 0.00001
        assert abs(expected_lonlat[basename][3] - desc["MAPAltitude"]) < 0.00001


def test_sample_video_relpath():
    if not is_ffmpeg_installed:
        pytest.skip("skip because ffmpeg not installed")

    with tempfile.TemporaryDirectory() as dir:
        x = subprocess.run(
            f"{EXECUTABLE} sample_video --rerun tests/data/gopro_data/hero8.mp4 {dir}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr


def test_sample_video_relpath_dir():
    if not is_ffmpeg_installed:
        pytest.skip("skip because ffmpeg not installed")

    with tempfile.TemporaryDirectory() as dir:
        x = subprocess.run(
            f"{EXECUTABLE} sample_video --rerun --video_start_time 2021_10_10_10_10_10_123 tests/integration {dir}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr


def test_sample_video_without_video_time(setup_data: py.path.local):
    if not is_ffmpeg_installed:
        pytest.skip("skip because ffmpeg not installed")

    video_dir = setup_data.join("videos")
    root_sample_dir = video_dir.join("mapillary_sampled_video_frames")

    for input_path in [video_dir, video_dir.join("sample-5s.mp4")]:
        x = subprocess.run(
            f"{EXECUTABLE} sample_video --rerun {input_path}",
            shell=True,
        )
        assert x.returncode == 7, x.stderr
        if root_sample_dir.exists():
            assert len(root_sample_dir.listdir()) == 0

        x = subprocess.run(
            f"{EXECUTABLE} sample_video --skip_sample_errors --rerun {input_path}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
        if root_sample_dir.exists():
            assert len(root_sample_dir.listdir()) == 0

        x = subprocess.run(
            f"{EXECUTABLE} sample_video --video_start_time 2021_10_10_10_10_10_123 --rerun {input_path}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
        assert len(root_sample_dir.listdir()) == 1
        samples = root_sample_dir.join("sample-5s.mp4").listdir()
        samples.sort()
        times = []
        for s in samples:
            with s.open("rb") as fp:
                tags = exifread.process_file(fp)
                times.append(tags["EXIF DateTimeOriginal"].values)
        assert (
            "2021:10:10 10:10:10.123",
            "2021:10:10 10:10:12.123",
            "2021:10:10 10:10:14.123",
        ) == tuple(times)


def test_video_process(setup_data: py.path.local):
    if not is_ffmpeg_installed:
        pytest.skip("skip because ffmpeg not installed")

    video_dir = setup_data.join("videos")
    gpx_file = video_dir.join("test.gpx")
    desc_path = video_dir.join("my_samples").join("mapillary_image_description.json")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} --verbose video_process {PROCESS_FLAGS} --skip_process_errors --video_start_time 2018_06_08_13_23_34_123 --geotag_source gpx --geotag_source_path {gpx_file} {video_dir} {video_dir.join('my_samples')}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    with open(desc_path) as fp:
        descs = json.load(fp)
    assert 1 == len(find_desc_errors(descs))
    assert 2 == len(filter_out_errors(descs))


@pytest.mark.usefixtures("setup_config")
def test_video_process_and_upload(
    setup_upload: py.path.local, setup_data: py.path.local
):
    if not is_ffmpeg_installed:
        pytest.skip("skip because ffmpeg not installed")

    video_dir = setup_data.join("videos")
    gpx_file = video_dir.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} video_process_and_upload {PROCESS_FLAGS} --video_start_time 2018_06_08_13_23_34_123 --geotag_source gpx --geotag_source_path {gpx_file} --dry_run --user_name={USERNAME} {video_dir} {video_dir.join('my_samples')}",
        shell=True,
    )
    assert x.returncode != 0, x.stderr
    assert 0 == len(setup_upload.listdir())

    x = subprocess.run(
        f"{EXECUTABLE} video_process_and_upload {PROCESS_FLAGS} --video_start_time 2018_06_08_13_23_34_123 --geotag_source gpx --geotag_source_path {gpx_file} --skip_process_errors --dry_run --user_name={USERNAME} {video_dir} {video_dir.join('my_samples')}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert 2 == len(setup_upload.listdir())
    for z in setup_upload.listdir():
        validate_and_extract_zip(str(z))


def test_video_process_multiple_videos(setup_data: py.path.local):
    if not is_ffmpeg_installed:
        pytest.skip("skip because ffmpeg not installed")

    gpx_file = setup_data.join("test.gpx")
    desc_path = setup_data.join("my_samples").join("mapillary_image_description.json")
    sub_folder = setup_data.join("video_sub_folder").mkdir()
    video_path = setup_data.join("videos").join("sample-5s.mp4")
    video_path.copy(sub_folder)
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} video_process {PROCESS_FLAGS} --video_start_time 2018_06_08_13_23_34_123 --geotag_source gpx --geotag_source_path {gpx_file} {video_path} {setup_data.join('my_samples')}",
        shell=True,
    )
    assert x.returncode != 0, x.stderr
    with open(desc_path) as fp:
        descs = json.load(fp)
    for d in descs:
        assert Path(d["filename"]).is_file(), d["filename"]
        assert "sample-5s.mp4" in d["filename"]
    assert 1 == len(find_desc_errors(descs))
    assert 2 == len(filter_out_errors(descs))
