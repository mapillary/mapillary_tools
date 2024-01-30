import datetime
import json
import subprocess
import tempfile
from pathlib import Path

import exifread
import py.path
import pytest

from .fixtures import (
    EXECUTABLE,
    IS_FFMPEG_INSTALLED,
    run_exiftool_and_generate_geotag_args,
    setup_config,
    setup_data,
    setup_upload,
    USERNAME,
    validate_and_extract_zip,
    verify_descs,
)


PROCESS_FLAGS = "--add_import_date"

_DEFAULT_EXPECTED_DESCS = {
    "DSC00001.JPG": {
        "filename": "DSC00001.JPG",
        "filetype": "image",
        "MAPLatitude": 45.5169031,
        "MAPLongitude": -122.572765,
        "MAPCaptureTime": "2018_06_08_20_24_11_000",
        "MAPAltitude": 70.3,
        "MAPCompassHeading": {"TrueHeading": 270.89, "MagneticHeading": 270.89},
        "MAPDeviceMake": "SONY",
        "MAPDeviceModel": "HDR-AS300",
        "MAPOrientation": 1,
    },
    "DSC00497.JPG": {
        "filename": "DSC00497.JPG",
        "filetype": "image",
        "MAPLatitude": 45.5107231,
        "MAPLongitude": -122.5760514,
        "MAPCaptureTime": "2018_06_08_20_32_28_000",
        "MAPAltitude": 77.5,
        "MAPCompassHeading": {"TrueHeading": 271.27, "MagneticHeading": 271.27},
        "MAPDeviceMake": "SONY",
        "MAPDeviceModel": "HDR-AS300",
        "MAPOrientation": 1,
    },
    "V0370574.JPG": {
        "filename": "V0370574.JPG",
        "filetype": "image",
        "MAPLatitude": -1.0169444,
        "MAPLongitude": -1.0169444,
        "MAPCaptureTime": "2018_07_27_11_32_14_000",
        "MAPCompassHeading": {"TrueHeading": 359.0, "MagneticHeading": 359.0},
        "MAPDeviceMake": "Garmin",
        "MAPDeviceModel": "VIRB 360",
        "MAPOrientation": 1,
    },
    "adobe_coords.jpg": {
        "filetype": "image",
        "MAPLatitude": -0.0702668,
        "MAPLongitude": 34.3819352,
        "MAPCaptureTime": "2019_07_16_10_26_11_000",
        "MAPCompassHeading": {"TrueHeading": 0, "MagneticHeading": 0},
        "MAPDeviceMake": "SAMSUNG",
        "MAPDeviceModel": "SM-C200",
        "MAPOrientation": 1,
    },
}


def test_basic():
    for option in ["--version", "--help"]:
        x = subprocess.run(f"{EXECUTABLE} {option}", shell=True)
        assert x.returncode == 0, x.stderr


def _local_to_utc(ct: str):
    return (
        datetime.datetime.fromisoformat(ct)
        .astimezone(datetime.timezone.utc)
        .strftime("%Y_%m_%d_%H_%M_%S_%f")[:-3]
    )


def test_process_images_with_defaults(
    setup_data: py.path.local,
    use_exiftool: bool = False,
):
    args = f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data}"
    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)
    x = subprocess.run(args, shell=True)

    assert x.returncode == 0, x.stderr
    verify_descs(
        [
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00001.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00001.JPG")),
            },
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00497.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00497.JPG")),
            },
            {
                **_DEFAULT_EXPECTED_DESCS["V0370574.JPG"],
                "filename": str(Path(setup_data, "images", "V0370574.JPG")),
                "MAPCaptureTime": _local_to_utc("2018-07-27T11:32:14"),
            },
        ],
        Path(setup_data, "mapillary_image_description.json"),
    )


def test_process_images_with_defaults_with_exiftool(setup_data: py.path.local):
    return test_process_images_with_defaults(setup_data, use_exiftool=True)


def test_time_with_offset(setup_data: py.path.local, use_exiftool: bool = False):
    args = f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --offset_time=2.5"
    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)
    x = subprocess.run(args, shell=True)
    assert x.returncode == 0, x.stderr
    verify_descs(
        [
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00001.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00001.JPG")),
                "MAPCaptureTime": "2018_06_08_20_24_13_500",
            },
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00497.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00497.JPG")),
                "MAPCaptureTime": "2018_06_08_20_32_30_500",
            },
            {
                **_DEFAULT_EXPECTED_DESCS["V0370574.JPG"],
                "filename": str(Path(setup_data, "images", "V0370574.JPG")),
                "MAPCaptureTime": _local_to_utc("2018-07-27T11:32:16.500"),
            },
        ],
        Path(setup_data, "mapillary_image_description.json"),
    )

    args = f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --offset_time=-1.0"
    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)
    x = subprocess.run(args, shell=True)
    assert x.returncode == 0, x.stderr
    verify_descs(
        [
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00001.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00001.JPG")),
                "MAPCaptureTime": "2018_06_08_20_24_10_000",
            },
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00497.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00497.JPG")),
                "MAPCaptureTime": "2018_06_08_20_32_27_000",
            },
            {
                **_DEFAULT_EXPECTED_DESCS["V0370574.JPG"],
                "filename": str(Path(setup_data, "images", "V0370574.JPG")),
                "MAPCaptureTime": _local_to_utc("2018-07-27T11:32:13.000"),
            },
        ],
        Path(setup_data, "mapillary_image_description.json"),
    )


def test_time_with_offset_with_exiftool(setup_data: py.path.local):
    return test_time_with_offset(setup_data, use_exiftool=True)


def test_process_images_with_overwrite_all_EXIF_tags(
    setup_data: py.path.local, use_exiftool: bool = False
):
    args = f"{EXECUTABLE} process --file_types=image --overwrite_all_EXIF_tags --offset_time=2.5 {PROCESS_FLAGS} {setup_data}"
    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)
    x = subprocess.run(args, shell=True)
    assert x.returncode == 0, x.stderr
    expected_descs = [
        {
            **_DEFAULT_EXPECTED_DESCS["DSC00001.JPG"],  # type: ignore
            "filename": str(Path(setup_data, "images", "DSC00001.JPG")),
            "MAPCaptureTime": "2018_06_08_20_24_13_500",
        },
        {
            **_DEFAULT_EXPECTED_DESCS["DSC00497.JPG"],  # type: ignore
            "filename": str(Path(setup_data, "images", "DSC00497.JPG")),
            "MAPCaptureTime": "2018_06_08_20_32_30_500",
        },
        {
            **_DEFAULT_EXPECTED_DESCS["V0370574.JPG"],
            "filename": str(Path(setup_data, "images", "V0370574.JPG")),
            "MAPCaptureTime": _local_to_utc("2018-07-27T11:32:16.500"),
        },
    ]
    verify_descs(
        expected_descs,
        Path(setup_data, "mapillary_image_description.json"),
    )

    args = f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data}"
    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)
    x = subprocess.run(args, shell=True)
    assert x.returncode == 0, x.stderr
    verify_descs(
        expected_descs,
        Path(setup_data, "mapillary_image_description.json"),
    )


def test_process_images_with_overwrite_all_EXIF_tags_with_exiftool(
    setup_data: py.path.local,
):
    return test_process_images_with_overwrite_all_EXIF_tags(
        setup_data, use_exiftool=True
    )


def test_angle_with_offset(setup_data: py.path.local, use_exiftool: bool = False):
    args = f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --offset_angle=2.5"
    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)
    x = subprocess.run(args, shell=True)
    assert x.returncode == 0, x.stderr

    verify_descs(
        [
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00001.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00001.JPG")),
                "MAPCompassHeading": {
                    "TrueHeading": 270.89 + 2.5,
                    "MagneticHeading": 270.89 + 2.5,
                },
            },
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00497.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00497.JPG")),
                "MAPCompassHeading": {
                    "TrueHeading": 271.27 + 2.5,
                    "MagneticHeading": 271.27 + 2.5,
                },
            },
            {
                **_DEFAULT_EXPECTED_DESCS["V0370574.JPG"],
                "filename": str(Path(setup_data, "images", "V0370574.JPG")),
                "MAPCaptureTime": _local_to_utc("2018-07-27T11:32:14"),
                "MAPCompassHeading": {
                    "TrueHeading": 1.5,
                    "MagneticHeading": 1.5,
                },
            },
        ],
        Path(setup_data, "mapillary_image_description.json"),
    )


def test_angle_with_offset_with_exiftool(setup_data: py.path.local):
    return test_angle_with_offset(setup_data, use_exiftool=True)


def test_parse_adobe_coordinates(setup_data: py.path.local):
    args = f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data}/adobe_coords"
    x = subprocess.run(args, shell=True)
    verify_descs(
        [
            {
                "filename": str(Path(setup_data, "adobe_coords", "adobe_coords.jpg")),
                "filetype": "image",
                "MAPLatitude": -0.0702668,
                "MAPLongitude": 34.3819352,
                "MAPCaptureTime": _local_to_utc("2019-07-16T10:26:11"),
                "MAPCompassHeading": {"TrueHeading": 0.0, "MagneticHeading": 0.0},
                "MAPDeviceMake": "SAMSUNG",
                "MAPDeviceModel": "SM-C200",
                "MAPOrientation": 1,
            }
        ],
        Path(setup_data, "adobe_coords/mapillary_image_description.json"),
    )


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
            <time>2018-06-08T20:23:34.805</time>
            </trkpt>

            <trkpt lat="2.02" lon="0.01">
            <ele>2</ele>
            <time>2018-06-08T20:24:35.809</time>
            </trkpt>

            <trkpt lat="2.02" lon="2.01">
            <ele>4</ele>
            <time>2018-06-08T20:33:36.813</time>
            </trkpt>

            <trkpt lat="4.02" lon="2.01">
            <ele>9</ele>
            <time>2018-06-08T20:58:37.812</time>
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
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --geotag_source gpx --geotag_source_path {gpx_file} --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    verify_descs(
        [
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00001.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00001.JPG")),
                "MAPLatitude": 1.2066435,
                "MAPLongitude": 0.01,
                "MAPAltitude": 1.593,
                "MAPCompassHeading": {"TrueHeading": 0.0, "MagneticHeading": 0.0},
            },
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00497.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00497.JPG")),
                "MAPLatitude": 2.02,
                "MAPLongitude": 1.75561,
                "MAPAltitude": 3.746,
                "MAPCompassHeading": {"TrueHeading": 89.965, "MagneticHeading": 89.965},
            },
            {
                "filename": str(Path(setup_data, "images", "V0370574.JPG")),
                "error": {
                    "type": "MapillaryOutsideGPXTrackError",
                },
            },
        ],
        Path(setup_data, "mapillary_image_description.json"),
    )


def test_geotagging_from_gpx_with_offset(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --geotag_source gpx --geotag_source_path {gpx_file} --interpolation_offset_time=-20 --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    verify_descs(
        [
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00001.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00001.JPG")),
                "MAPLatitude": 0.5509488,
                "MAPLongitude": 0.01,
                "MAPCaptureTime": "2018_06_08_20_23_51_000",
                "MAPAltitude": 1.265,
                "MAPCompassHeading": {"TrueHeading": 0.0, "MagneticHeading": 0.0},
            },
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00497.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00497.JPG")),
                "MAPLatitude": 2.02,
                "MAPLongitude": 1.6816734,
                "MAPCaptureTime": "2018_06_08_20_32_08_000",
                "MAPAltitude": 3.672,
                "MAPCompassHeading": {"TrueHeading": 89.965, "MagneticHeading": 89.965},
            },
            {
                "filename": str(Path(setup_data, "images", "V0370574.JPG")),
                "error": {
                    "type": "MapillaryOutsideGPXTrackError",
                },
            },
        ],
        Path(setup_data, "mapillary_image_description.json"),
    )


def test_geotagging_from_gpx_use_gpx_start_time(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --geotag_source gpx --interpolation_use_gpx_start_time --geotag_source_path {gpx_file} --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    verify_descs(
        [
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00001.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00001.JPG")),
                "MAPLatitude": 0.02,
                "MAPLongitude": 0.01,
                "MAPCaptureTime": "2018_06_08_20_23_34_805",
                "MAPAltitude": 1.0,
                "MAPCompassHeading": {"TrueHeading": 0.0, "MagneticHeading": 0.0},
            },
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00497.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00497.JPG")),
                "MAPLatitude": 2.02,
                "MAPLongitude": 1.6218032,
                "MAPCaptureTime": "2018_06_08_20_31_51_805",
                "MAPAltitude": 3.612,
                "MAPCompassHeading": {"TrueHeading": 89.965, "MagneticHeading": 89.965},
            },
            {
                "filename": str(Path(setup_data, "images", "V0370574.JPG")),
                "error": {
                    "type": "MapillaryOutsideGPXTrackError",
                },
            },
        ],
        Path(setup_data, "mapillary_image_description.json"),
    )


def test_geotagging_from_gpx_use_gpx_start_time_with_offset(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process --file_types=image {PROCESS_FLAGS} {setup_data} --geotag_source gpx --interpolation_use_gpx_start_time --geotag_source_path {gpx_file} --interpolation_offset_time=100 --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    verify_descs(
        [
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00001.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00001.JPG")),
                "MAPLatitude": 2.02,
                "MAPLongitude": 0.1541616,
                "MAPCaptureTime": "2018_06_08_20_25_14_805",
                "MAPAltitude": 2.144,
                "MAPCompassHeading": {"TrueHeading": 89.965, "MagneticHeading": 89.965},
            },
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00497.JPG"],
                "filename": str(Path(setup_data, "images", "DSC00497.JPG")),
                "MAPLatitude": 2.02,
                "MAPLongitude": 1.9914863,
                "MAPCaptureTime": "2018_06_08_20_33_31_805",
                "MAPAltitude": 3.981,
                "MAPCompassHeading": {"TrueHeading": 89.965, "MagneticHeading": 89.965},
            },
            {
                "filename": str(Path(setup_data, "images", "V0370574.JPG")),
                "error": {
                    "type": "MapillaryOutsideGPXTrackError",
                },
            },
        ],
        Path(setup_data, "mapillary_image_description.json"),
    )


def test_process_filetypes(setup_data: py.path.local):
    video_dir = setup_data.join("gopro_data")
    x = subprocess.run(
        f"{EXECUTABLE} --verbose process {PROCESS_FLAGS} --skip_process_errors {video_dir}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = video_dir.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
    assert 2 == len(descs)
    assert 1 == len(find_desc_errors(descs))
    assert 1 == len(filter_out_errors(descs))


def test_process_unsupported_filetypes(setup_data: py.path.local):
    video_dir = setup_data.join("gopro_data")
    for filetypes in ["blackvue"]:
        x = subprocess.run(
            f"{EXECUTABLE} --verbose process --filetypes={filetypes} {PROCESS_FLAGS} --skip_process_errors {video_dir}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
        desc_path = video_dir.join("mapillary_image_description.json")
        with open(desc_path) as fp:
            descs = json.load(fp)
        assert 2 == len(descs)
        assert 2 == len(find_desc_errors(descs))

    for filetypes in ["image"]:
        x = subprocess.run(
            f"{EXECUTABLE} --verbose process --filetypes={filetypes} {PROCESS_FLAGS} --skip_process_errors {video_dir}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
        desc_path = video_dir.join("mapillary_image_description.json")
        with open(desc_path) as fp:
            descs = json.load(fp)
        assert 0 == len(descs)


def test_sample_video_relpath():
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("skip because ffmpeg not installed")

    with tempfile.TemporaryDirectory() as dir:
        x = subprocess.run(
            f"{EXECUTABLE} sample_video --rerun tests/data/gopro_data/hero8.mp4 {dir}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr


def test_sample_video_relpath_dir():
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("skip because ffmpeg not installed")

    with tempfile.TemporaryDirectory() as dir:
        x = subprocess.run(
            f"{EXECUTABLE} sample_video --rerun --video_start_time 2021_10_10_10_10_10_123 tests/integration {dir}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr


def test_sample_video_without_video_time(setup_data: py.path.local):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("skip because ffmpeg not installed")

    video_dir = setup_data.join("videos")
    root_sample_dir = video_dir.join("mapillary_sampled_video_frames")

    for input_path in [video_dir, video_dir.join("sample-5s.mp4")]:
        x = subprocess.run(
            f"{EXECUTABLE} sample_video --video_sample_interval=2 --video_sample_distance=-1 --video_sample_distance=-1 --rerun {input_path}",
            shell=True,
        )
        assert x.returncode == 7, x.stderr
        if root_sample_dir.exists():
            assert len(root_sample_dir.listdir()) == 0

        x = subprocess.run(
            f"{EXECUTABLE} sample_video --video_sample_interval=2 --video_sample_distance=-1 --skip_sample_errors --rerun {input_path}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
        if root_sample_dir.exists():
            assert len(root_sample_dir.listdir()) == 0

        x = subprocess.run(
            f"{EXECUTABLE} sample_video --video_sample_interval=2 --video_sample_distance=-1 --video_start_time 2021_10_10_10_10_10_123 --rerun {input_path}",
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
            "2021:10:10 10:10:10",
            "2021:10:10 10:10:12",
            "2021:10:10 10:10:14",
        ) == tuple(times)


def test_video_process(setup_data: py.path.local):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("skip because ffmpeg not installed")

    video_dir = setup_data.join("videos")
    gpx_file = video_dir.join("test.gpx")
    desc_path = video_dir.join("my_samples").join("mapillary_image_description.json")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} --verbose video_process --video_sample_interval=2 --video_sample_distance=-1 {PROCESS_FLAGS} --skip_process_errors --video_start_time 2018_06_08_20_23_34_123 --geotag_source gpx --geotag_source_path {gpx_file} {video_dir} {video_dir.join('my_samples')}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    with open(desc_path) as fp:
        descs = json.load(fp)
    assert 1 == len(find_desc_errors(descs))
    assert 2 == len(filter_out_errors(descs))


def test_video_process_sample_with_multiple_distances(setup_data: py.path.local):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("skip because ffmpeg not installed")

    video_dir = setup_data.join("gopro_data")
    desc_path = video_dir.join("my_samples").join("mapillary_image_description.json")
    for distance in [0, 2.4, 100]:
        x = subprocess.run(
            f"{EXECUTABLE} --verbose video_process --video_sample_distance={distance} --rerun {PROCESS_FLAGS} {video_dir} {video_dir.join('my_samples')}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
        with open(desc_path) as fp:
            descs = json.load(fp)
        if distance == 100:
            assert 1 == len(descs)
        else:
            assert len(descs) > 1


def test_video_process_sample_with_distance(setup_data: py.path.local):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("skip because ffmpeg not installed")

    video_dir = setup_data.join("gopro_data")
    sample_dir = Path(setup_data, "gopro_data", "my_samples")
    desc_path = Path(sample_dir, "mapillary_image_description.json")
    for option in [
        "--video_sample_distance=6",
        "--video_sample_distance=6 --video_sample_interval=-2",
    ]:
        x = subprocess.run(
            f"{EXECUTABLE} --verbose video_process {option} {PROCESS_FLAGS} {video_dir} {video_dir.join('my_samples')}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
        verify_descs(
            [
                {
                    "filename": str(
                        Path(
                            sample_dir,
                            "max-360mode.mp4",
                            "max-360mode_0_000001.jpg",
                        )
                    ),
                    "filetype": "image",
                    "MAPLatitude": 33.1266719,
                    "MAPLongitude": -117.3273063,
                    "MAPCaptureTime": "2019_11_18_15_44_47_862",
                    "MAPAltitude": -22.18,
                    "MAPCompassHeading": {
                        "TrueHeading": 313.68,
                        "MagneticHeading": 313.68,
                    },
                    "MAPSequenceUUID": "0",
                    "MAPDeviceMake": "GoPro",
                    "MAPDeviceModel": "GoPro Max",
                    "MAPOrientation": 1,
                },
                {
                    "filename": str(
                        Path(
                            sample_dir,
                            "max-360mode.mp4",
                            "max-360mode_0_000002.jpg",
                        )
                    ),
                    "filetype": "image",
                    "MAPLatitude": 33.1267206,
                    "MAPLongitude": -117.3273345,
                    "MAPCaptureTime": "2019_11_18_15_44_53_159",
                    "MAPAltitude": -21.91,
                    "MAPCompassHeading": {
                        "TrueHeading": 330.82,
                        "MagneticHeading": 330.82,
                    },
                    "MAPSequenceUUID": "0",
                    "MAPDeviceMake": "GoPro",
                    "MAPDeviceModel": "GoPro Max",
                    "MAPOrientation": 1,
                },
                {
                    "filename": str(
                        Path(
                            sample_dir,
                            "max-360mode.mp4",
                            "max-360mode_0_000003.jpg",
                        )
                    ),
                    "filetype": "image",
                    "MAPLatitude": 33.1267702,
                    "MAPLongitude": -117.3273612,
                    "MAPCaptureTime": "2019_11_18_15_44_58_289",
                    "MAPAltitude": -22.58,
                    "MAPCompassHeading": {
                        "TrueHeading": 10.54,
                        "MagneticHeading": 10.54,
                    },
                    "MAPSequenceUUID": "0",
                    "MAPDeviceMake": "GoPro",
                    "MAPDeviceModel": "GoPro Max",
                    "MAPOrientation": 1,
                },
            ],
            desc_path,
        )


@pytest.mark.usefixtures("setup_config")
def test_video_process_and_upload(
    setup_upload: py.path.local, setup_data: py.path.local
):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("skip because ffmpeg not installed")

    video_dir = setup_data.join("videos")
    gpx_file = video_dir.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} video_process_and_upload {PROCESS_FLAGS} --video_sample_interval=2 --video_sample_distance=-1 --video_start_time 2018_06_08_20_23_34_123 --geotag_source gpx --geotag_source_path {gpx_file} --dry_run --user_name={USERNAME} {video_dir} {video_dir.join('my_samples')}",
        shell=True,
    )
    assert x.returncode != 0, x.stderr
    assert 0 == len(setup_upload.listdir())

    x = subprocess.run(
        f"{EXECUTABLE} video_process_and_upload {PROCESS_FLAGS} --video_sample_interval=2 --video_sample_distance=-1 --video_start_time 2018_06_08_20_23_34_123 --geotag_source gpx --geotag_source_path {gpx_file} --skip_process_errors --dry_run --user_name={USERNAME} {video_dir} {video_dir.join('my_samples')}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert 2 == len(setup_upload.listdir())
    for z in setup_upload.listdir():
        validate_and_extract_zip(str(z))


def test_video_process_multiple_videos(setup_data: py.path.local):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("skip because ffmpeg not installed")

    gpx_file = setup_data.join("test.gpx")
    desc_path = setup_data.join("my_samples").join("mapillary_image_description.json")
    sub_folder = setup_data.join("video_sub_folder").mkdir()
    video_path = setup_data.join("videos").join("sample-5s.mp4")
    video_path.copy(sub_folder)
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} video_process {PROCESS_FLAGS} --video_sample_interval=2 --video_sample_distance=-1 --video_start_time 2018_06_08_20_23_34_123 --geotag_source gpx --geotag_source_path {gpx_file} {video_path} {setup_data.join('my_samples')}",
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
