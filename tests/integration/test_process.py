# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import itertools
import json
import os
import re
import subprocess
from pathlib import Path

import gpxpy
import py.path
import pytest

from .fixtures import (
    assert_contains_image_descs,
    assert_descs_exact_equal,
    EXECUTABLE,
    EXIFTOOL_EXECUTABLE,
    pytest_skip_if_not_exiftool_installed,
    run_command,
    run_exiftool_and_generate_geotag_args,
    run_exiftool_dir,
    run_process_for_descs,
    setup_data,
    validate_and_extract_zip,
)


_DEFAULT_EXPECTED_DESCS = {
    "DSC00001.JPG": {
        "filename": "DSC00001.JPG",
        "filetype": "image",
        "MAPFilename": "DSC00001.JPG",
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
        "MAPFilename": "DSC00497.JPG",
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
        "MAPFilename": "V0370574.JPG",
        "MAPLatitude": -1.0169444,
        "MAPLongitude": -1.0169444,
        "MAPCaptureTime": "2018_07_27_11_32_14_000",
        "MAPCompassHeading": {"TrueHeading": 359.0, "MagneticHeading": 359.0},
        "MAPDeviceMake": "Garmin",
        "MAPDeviceModel": "VIRB 360",
        "MAPOrientation": 1,
    },
    "adobe_coords.jpg": {
        "filename": "adobe_coords.jpg",
        "filetype": "image",
        "MAPFilename": "adobe_coords.jpg",
        "MAPLatitude": -0.0702668,
        "MAPLongitude": 34.3819352,
        "MAPCaptureTime": "2019_07_16_10_26_11_000",
        "MAPCompassHeading": {"TrueHeading": 0, "MagneticHeading": 0},
        "MAPDeviceMake": "SAMSUNG",
        "MAPDeviceModel": "SM-C200",
        "MAPOrientation": 1,
    },
}


def _local_to_utc(ct: str):
    return (
        datetime.datetime.fromisoformat(ct)
        .astimezone(datetime.timezone.utc)
        .strftime("%Y_%m_%d_%H_%M_%S_%f")[:-3]
    )


def test_basic():
    for option in ["--version", "--help"]:
        x = subprocess.run(f"{EXECUTABLE} {option}", shell=True)
        assert x.returncode == 0, x.stderr


def test_process_images_with_defaults(
    setup_data: py.path.local, use_exiftool: bool = False
):
    args = ["--file_types=image", str(setup_data)]
    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)

    descs = run_process_for_descs(args)

    assert_contains_image_descs(
        descs,
        [
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00001.JPG"],
            },
            {
                **_DEFAULT_EXPECTED_DESCS["DSC00497.JPG"],
            },
            {
                **_DEFAULT_EXPECTED_DESCS["V0370574.JPG"],
                "MAPCaptureTime": _local_to_utc("2018-07-27T11:32:14"),
            },
        ],
    )


def test_process_images_with_defaults_with_exiftool(setup_data: py.path.local):
    return test_process_images_with_defaults(setup_data, use_exiftool=True)


def test_time_with_offset(setup_data: py.path.local, use_exiftool: bool = False):
    args = ["--file_types=image", "--offset_time=2.5", str(setup_data)]

    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)

    descs = run_process_for_descs(args)

    assert_contains_image_descs(
        descs,
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
    )

    args = ["--file_types=image", str(setup_data), "--offset_time=-1.0"]
    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)

    descs = run_process_for_descs(args)
    assert_contains_image_descs(
        descs,
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
    )


def test_time_with_offset_with_exiftool(setup_data: py.path.local):
    return test_time_with_offset(setup_data, use_exiftool=True)


def test_process_images_with_overwrite_all_EXIF_tags(
    setup_data: py.path.local, use_exiftool: bool = False
):
    args = [
        "--file_types=image",
        "--overwrite_all_EXIF_tags",
        "--offset_time=2.5",
        str(setup_data),
    ]
    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)

    actual_descs = run_process_for_descs(args)

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
    assert_contains_image_descs(
        actual_descs,
        expected_descs,
    )

    args = ["--file_types=image", str(setup_data)]
    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)
    descs = run_process_for_descs(args)
    assert_contains_image_descs(descs, expected_descs)


def test_process_images_with_overwrite_all_EXIF_tags_with_exiftool(
    setup_data: py.path.local,
):
    return test_process_images_with_overwrite_all_EXIF_tags(
        setup_data, use_exiftool=True
    )


def test_angle_with_offset(setup_data: py.path.local, use_exiftool: bool = False):
    args = ["--file_types=image", str(setup_data), "--offset_angle=2.5"]

    if use_exiftool:
        args = run_exiftool_and_generate_geotag_args(setup_data, args)

    descs = run_process_for_descs(args)

    assert_contains_image_descs(
        descs,
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
    )


def test_angle_with_offset_with_exiftool(setup_data: py.path.local):
    return test_angle_with_offset(setup_data, use_exiftool=True)


def test_parse_adobe_coordinates(setup_data: py.path.local):
    args = ["--file_types=image", str(setup_data.join("adobe_coords"))]
    descs = run_process_for_descs(args)
    assert_contains_image_descs(
        descs,
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
    )


def test_zip_ok(tmpdir: py.path.local, setup_data: py.path.local):
    # Generate description file in the setup_data directory
    run_command(["--file_types=image", str(setup_data)], command="process")

    zip_dir = tmpdir.mkdir("zip_dir")
    run_command([str(setup_data), str(zip_dir)], command="zip")
    assert 0 < len(zip_dir.listdir())
    for file in zip_dir.listdir():
        validate_and_extract_zip(Path(file))


def test_zip_desc_not_found(tmpdir: py.path.local, setup_data: py.path.local):
    zip_dir = tmpdir.mkdir("zip_dir")
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_command([str(setup_data), str(zip_dir)], command="zip")
    assert exc_info.value.returncode == 3


def test_process_boolean_options(setup_data: py.path.local):
    boolean_options = [
        "--interpolate_directions",
        "--overwrite_EXIF_direction_tag",
        "--overwrite_EXIF_gps_tag",
        "--overwrite_EXIF_orientation_tag",
        "--overwrite_EXIF_time_tag",
        "--overwrite_all_EXIF_tags",
        "--skip_subfolders",
    ]
    for option in boolean_options:
        run_process_for_descs(
            [
                "--file_types=image",
                option,
                str(setup_data),
            ]
        )
    run_process_for_descs(
        [
            "--file_types=image",
            *boolean_options,
            str(setup_data),
        ]
    )


GPX_CONTENT = """
    <gpx>
    <trk>
        <name>Mapillary GPX</name>
        <trkseg>
            <trkpt lat="0.02" lon="0.01">
            <ele>1</ele>
            <time>2018-06-08T20:23:34.805Z</time>
            </trkpt>

            <trkpt lat="2.02" lon="0.01">
            <ele>2</ele>
            <time>2018-06-08T20:24:35.809Z</time>
            </trkpt>

            <trkpt lat="2.02" lon="2.01">
            <ele>4</ele>
            <time>2018-06-08T20:33:36.813Z</time>
            </trkpt>

            <trkpt lat="4.02" lon="2.01">
            <ele>9</ele>
            <time>2018-06-08T20:58:37.812Z</time>
            </trkpt>
        </trkseg>
    </trk>
    </gpx>
"""


def find_desc_errors(descs):
    return [desc for desc in descs if "error" in desc]


def filter_out_errors(descs):
    return [desc for desc in descs if "error" not in desc]


def test_geotagging_images_from_gpx(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    images = setup_data.join("images")

    descs = run_process_for_descs(
        [
            "--file_types=image",
            "--geotag_source=gpx",
            "--geotag_source_path",
            str(gpx_file),
            str(images),
        ]
    )

    assert_contains_image_descs(
        descs,
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
    )


def test_geotagging_images_from_malformed_gpx(setup_data: py.path.local):
    """Every image gets the error, as a video geotagged from the file does."""
    gpx_file = setup_data.join("test.gpx")
    gpx_file.write("<gpx><broken>")
    images = setup_data.join("images")

    descs = run_process_for_descs(
        [
            "--file_types=image",
            "--geotag_source=gpx",
            "--geotag_source_path",
            str(gpx_file),
            str(images),
        ]
    )

    assert sorted(Path(desc["filename"]).name for desc in descs) == [
        "DSC00001.JPG",
        "DSC00497.JPG",
        "V0370574.JPG",
    ]
    for desc in descs:
        assert desc["error"]["type"] == "MapillaryInvalidGPXError"
        # With the reason that gpxpy gives
        assert desc["error"]["message"].startswith(
            "test.gpx is not a valid GPX file: Error parsing XML: "
        )
        assert desc["error"]["message"].endswith(". Replace it with a valid GPX file.")


def test_geotagging_images_from_gpx_whose_times_cannot_be_read(
    setup_data: py.path.local,
):
    """It said only that no timestamped points were found"""
    gpx_file = setup_data.join("test.gpx")
    gpx_file.write(_with_unreadable_times(GPX_CONTENT))
    images = setup_data.join("images")

    descs = run_process_for_descs(
        [
            "--file_types=image",
            "--geotag_source=gpx",
            "--geotag_source_path",
            str(gpx_file),
            str(images),
        ]
    )

    assert len(descs) == 3
    for desc in descs:
        assert desc["error"] == {
            "type": "MapillaryInvalidGPXError",
            "message": (
                "test.gpx has no track point with a time that can be read: "
                "'2018-06-08T20:23:34.000.000Z' is not a GPX time, "
                "which looks like 2026-08-12T06:32:05.000Z"
            ),
        }


def test_geotagging_images_from_gpx_with_offset(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)

    descs = run_process_for_descs(
        [
            "--file_types=image",
            "--geotag_source=gpx",
            "--geotag_source_path",
            str(gpx_file),
            str(setup_data),
            "--interpolation_offset_time=-20",
        ]
    )
    assert_contains_image_descs(
        descs,
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
    )


def test_geotagging_images_from_gpx_use_gpx_start_time(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    descs = run_process_for_descs(
        [
            "--file_types=image",
            *["--geotag_source", "gpx"],
            "--interpolation_use_gpx_start_time",
            "--geotag_source_path",
            str(gpx_file),
            str(setup_data),
        ]
    )
    assert_contains_image_descs(
        descs,
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
    )


def test_geotagging_images_from_gpx_use_gpx_start_time_with_offset(
    setup_data: py.path.local,
):
    gpx_file = setup_data.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    descs = run_process_for_descs(
        [
            "--file_types=image",
            str(setup_data),
            *["--geotag_source", "gpx"],
            "--interpolation_use_gpx_start_time",
            "--geotag_source_path",
            str(gpx_file),
            "--interpolation_offset_time=100",
        ]
    )
    assert_contains_image_descs(
        descs,
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
    )


def test_process_filetypes(setup_data: py.path.local):
    video_dir = setup_data.join("gopro_data")
    descs = run_process_for_descs([str(video_dir)])
    assert 2 == len(descs)
    assert 1 == len(find_desc_errors(descs))
    assert 1 == len(filter_out_errors(descs))


def test_process_videos_with_an_image_only_geotag_source(setup_data: py.path.local):
    """exif cannot geotag videos: they are reported, not left out"""
    video_dir = setup_data.join("gopro_data")
    descs = run_process_for_descs(["--geotag_source=exif", str(video_dir)])
    assert 2 == len(descs)
    for desc in descs:
        assert desc["error"]["type"] == "MapillaryVideoGPSNotFoundError"
        assert desc["error"]["message"] == "The geotag source exif cannot geotag videos"


def test_process_unsupported_filetypes(setup_data: py.path.local):
    video_dir = setup_data.join("gopro_data")
    for filetypes in ["blackvue"]:
        # GoPro videos, which are not processed, as images are not
        descs = run_process_for_descs(
            ["--filetypes", filetypes, "--geotag_source=native", str(video_dir)]
        )
        assert 0 == len(descs)

    for filetypes in ["image"]:
        descs = run_process_for_descs(
            ["--filetypes", filetypes, "--geotag_source=native", str(video_dir)]
        )
        assert 0 == len(descs)


def test_process_filetypes_of_videos(setup_data: py.path.local):
    """
    The type of a video is known only once it is read. ExifTool, which the
    default sources fall back to, processed the videos of other types anyway
    """
    videos = [
        str(setup_data.join("gopro_data").join("max-360mode.mp4")),
        str(setup_data.join("videos").join("sample-5s.mp4")),
    ]
    descs = run_process_for_descs(["--filetypes=gopro", *videos])
    assert [(Path(d["filename"]).name, d["filetype"]) for d in descs] == [
        ("max-360mode.mp4", "gopro")
    ]
    assert "error" not in descs[0]

    assert [] == run_process_for_descs(["--filetypes=blackvue", *videos])

    # Limited by its own filetypes, a source leaves the video to the next
    descs = run_process_for_descs(
        [
            *[
                "--video_geotag_source",
                '{"source": "native", "filetypes": ["blackvue"]}',
            ],
            *["--video_geotag_source", "native"],
            videos[0],
        ]
    )
    assert [(Path(d["filename"]).name, d["filetype"]) for d in descs] == [
        ("max-360mode.mp4", "gopro")
    ]


def test_process_filetypes_of_videos_no_source_can_read(setup_data: py.path.local):
    """
    A video of a type asked for, given only sources that cannot geotag videos,
    is failed as without --filetypes. It was left out of the results
    """
    videos = [
        str(setup_data.join("gopro_data").join("max-360mode.mp4")),
        str(setup_data.join("videos").join("sample-5s.mp4")),
    ]
    descs = run_process_for_descs(
        ["--filetypes=gopro", "--geotag_source=exif", *videos]
    )
    assert [(Path(d["filename"]).name, d["error"]["message"]) for d in descs] == [
        ("max-360mode.mp4", "The geotag source exif cannot geotag videos")
    ]

    assert [] == run_process_for_descs(
        ["--filetypes=blackvue", "--geotag_source=exif", *videos]
    )


def test_process_filetypes_no_source_is_given(setup_data: py.path.local):
    """
    The filetypes of every source, limited to --filetypes if given, can leave
    out a file, which --filetypes lets in. It was left out of the results
    """
    videos = [
        str(setup_data.join("gopro_data").join("max-360mode.mp4")),
        str(setup_data.join("videos").join("sample-5s.mp4")),
    ]
    image_source = ['--geotag_source={"source": "native", "filetypes": ["image"]}']
    descs = run_process_for_descs([*image_source, *videos])
    assert sorted((Path(d["filename"]).name, d["error"]["message"]) for d in descs) == [
        (
            name,
            "No geotag source is given for this video: the geotag source native "
            "is limited to other file types",
        )
        for name in ["max-360mode.mp4", "sample-5s.mp4"]
    ]

    blackvue_source = [
        "--video_geotag_source",
        '{"source": "native", "filetypes": ["blackvue"]}',
    ]
    descs = run_process_for_descs(["--filetypes=gopro", *blackvue_source, *videos])
    assert [(Path(d["filename"]).name, d["error"]["message"]) for d in descs] == [
        (
            "max-360mode.mp4",
            "--filetypes gopro leaves no geotag source for this video: the geotag "
            "sources native, exiftool_runtime are limited to other file types",
        )
    ]

    image_dir = setup_data.join("images")
    video_source = ['--geotag_source={"source": "native", "filetypes": ["video"]}']
    descs = run_process_for_descs(["--filetypes=image", *video_source, str(image_dir)])
    assert descs
    assert {d["error"]["type"] for d in descs} == {"MapillaryGeoTaggingError"}


def test_process_image_not_a_frame_of_any_video(setup_data: py.path.local):
    """
    The legacy sources that geotag images from videos left out an image that is
    not a frame of any of the videos, as if it had not been given
    """
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    image_dir = setup_data.mkdir("frames")
    setup_data.join("images").join("DSC00001.JPG").copy(image_dir)
    legacy_source = [
        "--geotag_source=gopro_videos",
        f"--geotag_source_path={video_path}",
    ]

    descs = run_process_for_descs([*legacy_source, str(image_dir)])
    assert [(Path(d["filename"]).name, d["error"]) for d in descs] == [
        (
            "DSC00001.JPG",
            {
                "type": "MapillaryGeoTaggingError",
                "message": f"Not a frame of any video in {video_path}",
            },
        )
    ]

    # A later source can still geotag it
    descs = run_process_for_descs(
        [*legacy_source, "--geotag_source=exif", str(image_dir)]
    )
    assert [Path(d["filename"]).name for d in descs] == ["DSC00001.JPG"]
    assert "error" not in descs[0]


def test_process_video_geotag_source_with_gpx_specified(setup_data: py.path.local):
    video_path = setup_data.join("videos").join("sample-5s.mp4")
    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")

    descs = run_process_for_descs(
        [
            *[
                "--video_geotag_source",
                json.dumps({"source": "gpx", "source_path": str(gpx_file)}),
            ],
            str(video_path),
        ]
    )

    assert len(descs) == 1
    assert len(descs[0]["MAPGPSTrack"]) > 0
    assert descs[0]["filesize"] == 2848208


def test_process_video_geotag_source_gpx_not_found(setup_data: py.path.local):
    video_path = setup_data.join("videos").join("sample-5s.mp4")
    descs = run_process_for_descs(
        [
            *["--video_geotag_source", "gpx"],
            str(video_path),
        ]
    )

    assert len(descs) == 1
    assert descs[0]["error"]["type"] == "MapillaryVideoGPSNotFoundError"


# The GPS track of gopro_data/max-360mode.mp4 starts at 2019-11-18T23:44:42.59Z
_GOPRO_MAX_GPS_START = datetime.datetime(
    2019, 11, 18, 23, 44, 40, tzinfo=datetime.timezone.utc
)


def _copy_gpx_shifted_to(
    src: py.path.local, dst: py.path.local, start: datetime.datetime
) -> None:
    """Copy a GPX file with its times shifted to begin at start."""
    with open(src) as fp:
        gpx = gpxpy.parse(fp)
    start_time = gpx.get_time_bounds().start_time
    assert start_time is not None
    gpx.adjust_time(start - start_time)
    dst.write(gpx.to_xml())


def _with_unreadable_times(gpx: str, every: int = 1) -> str:
    """
    The GPX with every **every**th time written with two fractions, as
    2018-06-08T20:23:34.000.000Z, which gpxpy cannot read
    """
    count = itertools.count()
    return re.sub(
        r"<time>([^<.Z]+)(?:\.\d+)?Z</time>",
        lambda m: (
            f"<time>{m.group(1)}.000.000Z</time>"
            if next(count) % every == 0
            else m.group(0)
        ),
        gpx,
    )


def test_process_video_geotag_source_with_gopro_gpx_specified(
    setup_data: py.path.local,
):
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    gpx_file = setup_data.join("gpx").join("max-360mode.gpx")
    _copy_gpx_shifted_to(
        setup_data.join("gpx").join("sf_30km_h.gpx"), gpx_file, _GOPRO_MAX_GPS_START
    )

    descs = run_process_for_descs(
        [
            *[
                "--video_geotag_source",
                json.dumps({"source": "gpx", "source_path": str(gpx_file)}),
            ],
            str(video_path),
        ]
    )

    assert len(descs) == 1
    assert descs[0]["MAPDeviceMake"] == "GoPro"
    assert descs[0]["MAPDeviceModel"] == "GoPro Max"
    assert len(descs[0]["MAPGPSTrack"]) > 0


def test_process_video_geotag_source_with_gpx_outside_video(
    setup_data: py.path.local,
):
    """A GPX file recorded at another time than the video must not sync."""
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    # Recorded in 2025, five years after the video
    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")

    descs = run_process_for_descs(
        [
            *[
                "--video_geotag_source",
                json.dumps({"source": "gpx", "source_path": str(gpx_file)}),
            ],
            str(video_path),
        ]
    )

    assert len(descs) == 1
    assert descs[0]["error"]["type"] == "MapillaryOutsideGPXTrackError"
    assert descs[0]["error"]["vars"] == {
        # Its first GPS timestamp is 23:44:42.590, a second before the rest
        # place the start of the video
        "image_time": "2019_11_18_23_44_43_613",
        "gpx_start_time": "2025_03_14_07_00_00_000",
        "gpx_end_time": "2025_03_14_07_01_33_624",
    }


def test_process_video_from_gpx_with_interpolation_options(
    setup_data: py.path.local,
):
    """
    The interpolation options line up a GPX with a video, as they do with
    images. They were ignored for videos.
    """
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    # 3.613 seconds before the GPS clock of the video starts
    start = datetime.datetime(2019, 11, 18, 23, 44, 40, tzinfo=datetime.timezone.utc)
    points = "".join(
        f'<trkpt lat="{37.0 + i * 0.0001:.7f}" lon="-122.0">'
        f"<time>{(start + datetime.timedelta(seconds=i)).isoformat()}</time></trkpt>"
        for i in range(21)
    )
    gpx_file = setup_data.join("track.gpx")
    gpx_file.write(
        '<?xml version="1.0"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{points}</trkseg></trk></gpx>\n"
    )

    def describe(*options: str):
        [desc] = run_process_for_descs(
            [
                *["--geotag_source", "gpx"],
                *["--geotag_source_path", str(gpx_file)],
                *options,
                str(video_path),
            ]
        )
        return desc

    # The track is clipped to the video, so look a point up by its GPX time.
    # The video takes the times of its positions along the GPX, as images do,
    # so the point keeps that time whatever the options
    recorded = start.timestamp() + 10

    def video_time_of_recorded(*options: str) -> float:
        [point] = [p for p in describe(*options)["MAPGPSTrack"] if p[5] == recorded]
        return point[0]

    synced = video_time_of_recorded()
    assert synced == pytest.approx(10000 - 3613, abs=1)

    assert video_time_of_recorded("--interpolation_use_gpx_start_time") == 10000
    assert (
        video_time_of_recorded(
            "--interpolation_use_gpx_start_time", "--interpolation_offset_time=2.5"
        )
        == 7500
    )

    shifted = video_time_of_recorded("--interpolation_offset_time=2")
    assert shifted == pytest.approx(synced - 2000, abs=1)

    # an offset that moves the track off the video fails it, as it does a
    # track placed by the clock of the video
    error = describe(
        "--interpolation_use_gpx_start_time", "--interpolation_offset_time=60"
    )["error"]
    assert error["type"] == "MapillaryOutsideGPXTrackError"
    assert "by 40 seconds, as --interpolation_offset_time 60 " in error["message"]


def test_process_video_from_nmea(setup_data: py.path.local):
    """
    A video is geotagged from an NMEA file as from a GPX file of the same
    track. It got no description at all.
    """
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    start = datetime.datetime(2019, 11, 18, 23, 44, 40, tzinfo=datetime.timezone.utc)
    trkpts = []
    sentences = []
    for i in range(21):
        time = start + datetime.timedelta(seconds=i)
        trkpts.append(
            f'<trkpt lat="{37.0 + i / 6000:.9f}" lon="-122.0">'
            f"<time>{time.isoformat()}</time></trkpt>"
        )
        hhmmss = time.strftime("%H%M%S.00")
        position = f"3700.{i * 100:04d},N,12200.0000,W"
        for body in [
            f"GPRMC,{hhmmss},A,{position},0.0,0.0,{time.strftime('%d%m%y')},,,A",
            f"GPGGA,{hhmmss},{position},1,08,1.0,,M,,M,,",
        ]:
            checksum = 0
            for char in body:
                checksum ^= ord(char)
            sentences.append(f"${body}*{checksum:02X}\r\n")
    gpx_file = setup_data.join("track.gpx")
    gpx_file.write(
        '<?xml version="1.0"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{''.join(trkpts)}</trkseg></trk></gpx>\n"
    )
    nmea_file = setup_data.join("track.nmea")
    nmea_file.write("".join(sentences))

    def track(source: str, source_path: py.path.local):
        [desc] = run_process_for_descs(
            [
                *["--geotag_source", source],
                *["--geotag_source_path", str(source_path)],
                str(video_path),
            ]
        )
        return desc["MAPGPSTrack"]

    from_nmea = track("nmea", nmea_file)
    from_gpx = track("gpx", gpx_file)

    assert len(from_nmea) == len(from_gpx) > 0
    for nmea_point, gpx_point in zip(from_nmea, from_gpx):
        assert nmea_point == pytest.approx(gpx_point, abs=1e-6)


def test_process_video_from_nmea_with_some_checksums(setup_data: py.path.local):
    """
    Checksums are optional in NMEA. Where some sentences had one, those
    without were all taken for cut short, and the file failed
    """
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    start = datetime.datetime(2019, 11, 18, 23, 44, 40, tzinfo=datetime.timezone.utc)

    def write_nmea(name: str, with_checksum) -> py.path.local:
        sentences = []
        for i in range(21):
            time = start + datetime.timedelta(seconds=i)
            hhmmss = time.strftime("%H%M%S.00")
            position = f"3700.{i * 100:04d},N,12200.0000,W"
            for body in [
                f"GPRMC,{hhmmss},A,{position},0.0,0.0,{time.strftime('%d%m%y')},,,A",
                f"GPGGA,{hhmmss},{position},1,08,1.0,,M,,M,,",
            ]:
                checksum = 0
                for char in body:
                    checksum ^= ord(char)
                ending = f"*{checksum:02X}" if with_checksum(body) else ""
                sentences.append(f"${body}{ending}\r\n")
        nmea_file = setup_data.join(name)
        nmea_file.write_binary("".join(sentences).encode("ascii"))
        return nmea_file

    def track(nmea_file: py.path.local):
        [desc] = run_process_for_descs(
            [
                *["--geotag_source", "nmea"],
                *["--geotag_source_path", str(nmea_file)],
                str(video_path),
            ]
        )
        assert "error" not in desc, desc
        return desc["MAPGPSTrack"]

    every = track(write_nmea("every.nmea", lambda body: True))
    assert every
    assert track(write_nmea("gga.nmea", lambda body: body.startswith("GPGGA"))) == every
    assert track(write_nmea("one.nmea", lambda body: "234450" in body)) == every


def test_process_video_from_nmea_with_a_byte_order_mark(setup_data: py.path.local):
    """The byte order mark that some editors write cost the first sentence"""
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    start = datetime.datetime(2019, 11, 18, 23, 44, 40, tzinfo=datetime.timezone.utc)
    sentences = []
    for i in range(21):
        time = start + datetime.timedelta(seconds=i)
        hhmmss = time.strftime("%H%M%S.00")
        position = f"3700.{i * 100:04d},N,12200.0000,W"
        # GGA first, so that the first fix lost its position to the mark
        for body in [
            f"GPGGA,{hhmmss},{position},1,08,1.0,,M,,M,,",
            f"GPRMC,{hhmmss},A,{position},0.0,0.0,{time.strftime('%d%m%y')},,,A",
        ]:
            checksum = 0
            for char in body:
                checksum ^= ord(char)
            sentences.append(f"${body}*{checksum:02X}\r\n")
    content = "".join(sentences).encode("ascii")

    def track(name: str, data: bytes):
        nmea_file = setup_data.join(name)
        nmea_file.write_binary(data)
        desc_path = setup_data.join(f"{name}.json")
        result = run_command(
            [
                "--skip_process_errors",
                *["--desc_path", str(desc_path)],
                *["--geotag_source", "nmea"],
                *["--geotag_source_path", str(nmea_file)],
                str(video_path),
            ],
            "process",
            capture_output=True,
            text=True,
        )
        assert "malformed" not in result.stderr
        [desc] = json.loads(desc_path.read())
        assert "error" not in desc, desc
        return desc["MAPGPSTrack"]

    assert track("bom.nmea", b"\xef\xbb\xbf" + content) == track("plain.nmea", content)


def test_process_video_from_an_nmea_file_that_is_a_video(setup_data: py.path.local):
    """A video given as the NMEA file, which was decoded whole, fails at once"""
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")

    [desc] = run_process_for_descs(
        [
            *["--geotag_source", "nmea"],
            *["--geotag_source_path", str(video_path)],
            str(video_path),
        ]
    )

    assert desc["error"]["type"] == "MapillaryInvalidGPXError"
    assert (
        "max-360mode.mp4 is not a valid NMEA file: it is not text"
        in desc["error"]["message"]
    )


def test_process_geotag_with_gpx_pattern_not_found(setup_data: py.path.local):
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")

    descs = run_process_for_descs(
        [
            *["--video_geotag_source", "gpx"],
            str(video_path),
        ]
    )

    assert len(descs) == 1
    assert descs[0]["error"]["type"] == "MapillaryVideoGPSNotFoundError"


def test_process_geotag_with_gpx_pattern(setup_data: py.path.local):
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    _copy_gpx_shifted_to(
        setup_data.join("gpx").join("sf_30km_h.gpx"),
        setup_data.join("gopro_data").join("max-360mode.gpx"),
        _GOPRO_MAX_GPS_START,
    )

    descs = run_process_for_descs(
        [
            *["--video_geotag_source", "gpx"],
            str(video_path),
        ]
    )

    assert len(descs) == 1
    assert descs[0]["MAPDeviceMake"] == "GoPro"
    assert descs[0]["MAPDeviceModel"] == "GoPro Max"
    assert len(descs[0]["MAPGPSTrack"]) > 0


def test_process_geotag_with_malformed_gpx_pattern(setup_data: py.path.local):
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    gpx_file = setup_data.join("gopro_data").join("max-360mode.gpx")
    gpx_file.write("<gpx><broken>")

    descs = run_process_for_descs(
        [
            *[
                "--geotag_source",
                json.dumps({"source": "gpx", "filetypes": ["video"]}),
            ],
            *["--geotag_source", "native"],
            str(video_path),
        ]
    )

    video_desc = next(desc for desc in descs if desc["filename"] == str(video_path))
    assert video_desc["error"]["type"] == "MapillaryInvalidGPXError"
    # With the reason that gpxpy gives
    assert video_desc["error"]["message"].startswith(
        "max-360mode.gpx is not a valid GPX file: Error parsing XML: "
    )
    assert video_desc["error"]["message"].endswith(
        ". Replace it with a valid GPX file."
    )


def test_process_video_from_a_gpx_whose_times_cannot_be_read(
    setup_data: py.path.local,
):
    """
    It failed as a stationary video: gpxpy reads no time for such a point,
    and says nothing of it
    """
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    gpx_file = setup_data.join("gpx").join("max-360mode.gpx")
    _copy_gpx_shifted_to(
        setup_data.join("gpx").join("sf_30km_h.gpx"), gpx_file, _GOPRO_MAX_GPS_START
    )
    gpx_file.write(_with_unreadable_times(gpx_file.read()))

    [desc] = run_process_for_descs(
        [
            *["--video_geotag_source", "gpx"],
            *["--geotag_source_path", str(gpx_file)],
            str(video_path),
        ]
    )

    assert desc["error"] == {
        "type": "MapillaryInvalidGPXError",
        "message": (
            "max-360mode.gpx has no track point with a time that can be read: "
            "'2019-11-18T23:44:40.000.000Z' is not a GPX time, "
            "which looks like 2026-08-12T06:32:05.000Z"
        ),
    }


def test_process_video_from_a_gpx_with_some_times_that_cannot_be_read(
    setup_data: py.path.local,
):
    """The points with a time geotag the video, and the others are warned of"""
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    gpx_file = setup_data.join("gpx").join("max-360mode.gpx")
    _copy_gpx_shifted_to(
        setup_data.join("gpx").join("sf_30km_h.gpx"), gpx_file, _GOPRO_MAX_GPS_START
    )
    gpx_file.write(_with_unreadable_times(gpx_file.read(), every=2))

    result = run_command(
        [
            *["--video_geotag_source", "gpx"],
            *["--geotag_source_path", str(gpx_file)],
            *["--desc_path", "-"],
            str(video_path),
        ],
        command="process",
        capture_output=True,
        text=True,
    )

    # Once, as the path of the file may be written otherwise on Windows
    assert result.stderr.count("Ignoring 25 of the 49 points in the GPX file") == 1
    assert (
        "whose times cannot be read (e.g. '2019-11-18T23:44:40.000.000Z')"
        in result.stderr
    )
    [desc] = json.loads(result.stdout)
    assert "error" not in desc, desc
    assert len(desc["MAPGPSTrack"]) > 0


def test_process_video_geotag_source_with_exiftool_runtime(setup_data: py.path.local):
    pytest_skip_if_not_exiftool_installed()

    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")

    exiftool_descs = run_process_for_descs(
        [
            *["--video_geotag_source", json.dumps({"source": "exiftool"})],
            str(video_path),
        ]
    )

    assert len(exiftool_descs) == 1
    assert exiftool_descs[0]["MAPDeviceMake"] == "GoPro"
    assert exiftool_descs[0]["MAPDeviceModel"] == "GoPro Max"
    assert len(exiftool_descs[0]["MAPGPSTrack"]) > 0

    native_descs = run_process_for_descs(
        [
            *["--video_geotag_source", json.dumps({"source": "native"})],
            str(video_path),
        ]
    )

    assert_descs_exact_equal(exiftool_descs, native_descs)


def test_process_video_geotag_source_names_in_readme(setup_data: py.path.local):
    """
    The README names the source that reads a video's own GPS "video", and those
    that read one format of it "gopro", "camm" and "blackvue"
    """
    video_path = str(setup_data.join("gopro_data").join("max-360mode.mp4"))

    native_descs = run_process_for_descs(
        ["--video_geotag_source", "native", video_path]
    )
    assert "error" not in native_descs[0]

    for source in ["video", "gopro"]:
        descs = run_process_for_descs(["--video_geotag_source", source, video_path])
        assert_descs_exact_equal(native_descs, descs)

    # A GoPro video is of none of the other formats, which says so
    for source, name in [("camm", "CAMM"), ("blackvue", "BlackVue")]:
        descs = run_process_for_descs(["--video_geotag_source", source, video_path])
        assert [d["error"] for d in descs] == [
            {
                "type": "MapillaryVideoGPSNotFoundError",
                "message": f"Not a {name} video: the geotag source {source} reads {name} videos only",
            }
        ]


def test_process_video_geotag_source_with_exiftool_runtime_pattern(
    setup_data: py.path.local,
):
    """
    As the README geotags a stitched video by the original it was stitched
    from: exiftool_runtime reads the file that its pattern names after the video
    """
    pytest_skip_if_not_exiftool_installed()

    original_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    stitched_dir = setup_data.join("gopro_data").mkdir("stitched")
    # A video without GPS of its own, named after the original
    stitched_path = stitched_dir.join("max-360mode.mp4")
    setup_data.join("videos").join("sample-5s.mp4").copy(stitched_path)

    descs = run_process_for_descs(
        [
            *[
                "--video_geotag_source",
                json.dumps({"source": "exiftool_runtime", "pattern": "../%g.mp4"}),
            ],
            str(stitched_dir),
        ]
    )
    original_descs = run_process_for_descs(
        [*["--video_geotag_source", "exiftool_runtime"], str(original_path)]
    )

    assert [Path(d["filename"]).name for d in descs] == ["max-360mode.mp4"]
    assert Path(descs[0]["filename"]).parent.name == "stitched"
    assert descs[0]["MAPDeviceModel"] == "GoPro Max"
    assert len(descs[0]["MAPGPSTrack"]) > 0
    assert descs[0]["MAPGPSTrack"] == original_descs[0]["MAPGPSTrack"]

    # Without the pattern, the video's own metadata has no GPS
    descs = run_process_for_descs(
        [*["--video_geotag_source", "exiftool_runtime"], str(stitched_dir)]
    )
    assert descs[0]["error"]["type"] == "MapillaryVideoGPSNotFoundError"


def test_process_video_with_an_exiftool_runtime_track_far_longer_than_it_warns(
    setup_data: py.path.local,
):
    """
    The original that the pattern names has 11.6 seconds of GPS for the 5.76
    seconds of the video named after it: process warns, as for a GPX track,
    and goes on
    """
    pytest_skip_if_not_exiftool_installed()

    stitched_dir = setup_data.join("gopro_data").mkdir("stitched")
    setup_data.join("videos").join("sample-5s.mp4").copy(
        stitched_dir.join("max-360mode.mp4")
    )

    def stderr(source: dict, path: py.path.local) -> str:
        return run_command(
            [
                *["--video_geotag_source", json.dumps(source)],
                *["--desc_path", os.devnull],
                str(path),
            ],
            command="process",
            capture_output=True,
            text=True,
        ).stderr

    warned = stderr(
        {"source": "exiftool_runtime", "pattern": "../%g.mp4"}, stitched_dir
    )
    assert "lasts 11.6 seconds and the video" in warned
    assert "so the video could start anywhere along the track" in warned

    # The track of the original itself
    original_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    assert "could start anywhere" not in stderr(
        {"source": "exiftool_runtime"}, original_path
    )


def test_process_geotag_everything_with_exiftool_runtime(setup_data: py.path.local):
    pytest_skip_if_not_exiftool_installed()

    exiftool_descs = run_process_for_descs(
        [*["--geotag_source", "exiftool_runtime"], str(setup_data)]
    )

    native_descs = run_process_for_descs(
        [*["--geotag_source", "native"], str(setup_data)]
    )

    assert_descs_exact_equal(exiftool_descs, native_descs)


def test_process_geotag_everything_with_exiftool_not_found(setup_data: py.path.local):
    pytest_skip_if_not_exiftool_installed()

    env = os.environ.copy()
    env.update(
        {
            "MAPILLARY_TOOLS_EXIFTOOL_PATH": "exiftool_not_found",
        }
    )

    exiftool_descs = run_process_for_descs(
        [*["--geotag_source", "exiftool_runtime"], str(setup_data)], env=env
    )

    assert len(exiftool_descs) > 0
    for d in exiftool_descs:
        assert "error" in d
        assert d["error"]["type"] == "MapillaryExiftoolNotFoundError"


def test_process_geotag_everything_with_exiftool_not_found_overriden(
    setup_data: py.path.local,
):
    pytest_skip_if_not_exiftool_installed()

    env = os.environ.copy()
    env.update(
        {
            "MAPILLARY_TOOLS_EXIFTOOL_PATH": "exiftool_not_found",
        }
    )

    exiftool_descs = run_process_for_descs(
        [
            *["--geotag_source", "exiftool_runtime"],
            *["--geotag_source", "native"],
            str(setup_data),
        ],
        env=env,
    )

    native_descs = run_process_for_descs(
        [
            *["--geotag_source", "exiftool_runtime"],
            *["--geotag_source", "native"],
            str(setup_data),
        ],
        env=env,
    )

    assert_descs_exact_equal(exiftool_descs, native_descs)


def test_process_geotag_with_exiftool_xml(setup_data: py.path.local):
    pytest_skip_if_not_exiftool_installed()

    exiftool_output_dir = run_exiftool_dir(setup_data)

    exiftool_descs = run_process_for_descs(
        [
            *[
                "--geotag_source",
                json.dumps(
                    {"source": "exiftool_xml", "source_path": str(exiftool_output_dir)}
                ),
            ],
            str(setup_data),
        ]
    )

    native_descs = run_process_for_descs(
        [*["--geotag_source", "native"], str(setup_data)]
    )

    assert_descs_exact_equal(exiftool_descs, native_descs)


def test_process_geotag_with_exiftool_xml_pattern(setup_data: py.path.local):
    pytest_skip_if_not_exiftool_installed()

    exiftool_output_dir = run_exiftool_dir(setup_data)

    exiftool_descs = run_process_for_descs(
        [
            *[
                "--geotag_source",
                json.dumps(
                    {
                        "source": "exiftool_xml",
                        "pattern": str(exiftool_output_dir.join("%g.xml")),
                    }
                ),
            ],
            str(setup_data),
        ]
    )

    native_descs = run_process_for_descs(
        [*["--geotag_source", "native"], str(setup_data)]
    )

    assert_descs_exact_equal(exiftool_descs, native_descs)


def test_process_geotag_with_exiftool_xml_default_pattern(setup_data: py.path.local):
    """
    Without a source path or a pattern, exiftool_xml reads the XML named after
    each image and video, beside it: %g.xml, as the README documents
    """
    pytest_skip_if_not_exiftool_installed()

    paths = [
        str(setup_data.join("images")),
        str(setup_data.join("gopro_data").join("max-360mode.mp4")),
    ]
    subprocess.run(
        [
            EXIFTOOL_EXECUTABLE,
            *["-fast", "-q", "-n", "-X", "-ee"],
            *["-api", "LargeFileSupport=1"],
            *["-w!", "%d%f.xml"],
            *paths,
        ],
        check=True,
    )
    assert setup_data.join("gopro_data").join("max-360mode.xml").check()

    native_descs = run_process_for_descs([*["--geotag_source", "native"], *paths])

    descs = run_process_for_descs([*["--geotag_source", "exiftool_xml"], *paths])
    assert_descs_exact_equal(native_descs, descs)

    native_video_descs = run_process_for_descs(
        [*["--video_geotag_source", "native"], paths[1]]
    )
    video_descs = run_process_for_descs(
        [*["--video_geotag_source", "exiftool_xml"], paths[1]]
    )
    assert_descs_exact_equal(native_video_descs, video_descs)


def test_process_geotag_with_exiftool_xml_default_pattern_missing_file(
    setup_data: py.path.local,
):
    video_path = setup_data.join("videos").join("sample-5s.mp4")
    descs = run_process_for_descs(
        [*["--video_geotag_source", "exiftool_xml"], str(video_path)]
    )

    assert len(descs) == 1
    assert descs[0]["error"]["type"] == "MapillaryExifToolXMLNotFoundError"


def test_process_geotag_with_exiftool_xml_pattern_missing_file(
    setup_data: py.path.local,
):
    video_path = setup_data.join("videos").join("sample-5s.mp4")
    descs = run_process_for_descs(
        [
            *[
                "--geotag_source",
                json.dumps(
                    {
                        "source": "exiftool_xml",
                        "pattern": str(setup_data.join("gpx").join("%g.xml")),
                    }
                ),
            ],
            str(video_path),
        ]
    )

    assert len(descs) == 1
    assert descs[0]["error"]["type"] == "MapillaryExifToolXMLNotFoundError"


def test_process_geotag_with_exiftool_xml_pattern_fallback(
    setup_data: py.path.local,
):
    video_path = setup_data.join("videos").join("sample-5s.mp4")
    descs = run_process_for_descs(
        [
            *[
                "--geotag_source",
                json.dumps(
                    {
                        "source": "exiftool_xml",
                        "pattern": str(setup_data.join("gpx").join("%g.xml")),
                    }
                ),
            ],
            *["--geotag_source", "gpx"],
            *["--geotag_source", "native"],
            str(video_path),
        ]
    )

    assert len(descs) == 1
    assert descs[0]["error"]["type"] == "MapillaryVideoGPSNotFoundError"


def _write_track_parts(gpx_file: py.path.local, parts) -> None:
    """A GPX track of parts, each (start, seconds, lat) with a point a second"""
    points = "".join(
        f'<trkpt lat="{lat + i * 0.0001:.7f}" lon="-122.0">'
        f"<time>{(start + datetime.timedelta(seconds=i)).isoformat()}</time></trkpt>"
        for start, seconds, lat in parts
        for i in range(seconds + 1)
    )
    gpx_file.write(
        '<?xml version="1.0"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{points}</trkseg></trk></gpx>\n"
    )


def test_process_video_track_is_not_interpolated_across_a_gpx_gap(
    setup_data: py.path.local,
):
    """
    A video that starts in a gap of more than an hour of the GPX track takes
    the track from the first point past the gap: a point interpolated across
    the gap, at the start of the video, was uploaded with it
    """
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    # The GPS clock of the video starts at 23:44:43.613, and the track
    # resumes 3.387 seconds later, 2 hours after its previous point 5 km away
    resumed = datetime.datetime(2019, 11, 18, 23, 44, 47, tzinfo=datetime.timezone.utc)
    gpx_file = setup_data.join("track.gpx")
    _write_track_parts(
        gpx_file,
        [(resumed - datetime.timedelta(hours=2), 0, 37.045), (resumed, 20, 37.0)],
    )

    [desc] = run_process_for_descs(
        [
            *["--geotag_source", "gpx"],
            *["--geotag_source_path", str(gpx_file)],
            str(video_path),
        ]
    )

    track = desc["MAPGPSTrack"]
    assert track[0][0] == pytest.approx(3387, abs=1)
    assert track[0][2] == pytest.approx(37.0)


def test_process_video_with_a_gpx_gap_inside_it_fails(setup_data: py.path.local):
    """process would interpolate the track across it, which sampling leaves out"""
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    start = datetime.datetime(2019, 11, 18, 23, 44, 40, tzinfo=datetime.timezone.utc)
    gpx_file = setup_data.join("track.gpx")
    # No point from 4.4 to 9.4 seconds into the video
    _write_track_parts(
        gpx_file,
        [(start, 8, 37.0), (start + datetime.timedelta(seconds=13), 10, 37.001)],
    )

    [desc] = run_process_for_descs(
        [
            *["--geotag_source", "gpx"],
            *["--geotag_source_path", str(gpx_file)],
            str(video_path),
        ],
        env={**os.environ, "MAPILLARY_TOOLS_MAX_GPX_GAP_SECONDS": "3"},
    )

    assert desc["error"]["type"] == "MapillaryOutsideGPXTrackError"
    assert "has a gap of 5 seconds" in desc["error"]["message"]
    assert "Sample the video with video_process" in desc["error"]["message"]


def test_process_video_with_a_gpx_far_longer_than_it_warns(
    setup_data: py.path.local,
):
    """
    Without a GPS clock or a start time, the video is assumed to start with
    the track, which runs on for long after it: process warns, and goes on.
    """
    video_path = setup_data.join("videos").join("sample-5s.mp4")
    # 93 seconds of track for 5.76 seconds of video
    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")

    result = run_command(
        [
            *["--geotag_source", "gpx"],
            *["--geotag_source_path", str(gpx_file)],
            *["--desc_path", "-"],
            str(video_path),
        ],
        command="process",
        capture_output=True,
        text=True,
    )

    assert "could start anywhere along the track" in result.stderr
    [desc] = json.loads(result.stdout)
    assert desc["MAPGPSTrack"][0][0] == 0


def test_process_image_with_a_placeholder_capture_time_and_offset(
    tmpdir: py.path.local,
):
    """
    A camera without a clock writes 0001:01:01 00:00:00. With a time zone
    offset, that time is before year 1 in UTC, and crashed the run
    """
    from PIL import Image
    from PIL.ExifTags import Base, GPS, IFD
    from PIL.TiffImagePlugin import IFDRational

    folder = tmpdir.mkdir("images")
    for name, date in [
        ("placeholder.jpg", "0001:01:01 00:00:00"),
        ("valid.jpg", "2020:01:02 03:04:05"),
    ]:
        img = Image.new("RGB", (4, 4), (0, 0, 0))
        exif = img.getexif()
        exif.get_ifd(IFD.Exif)[Base.DateTimeOriginal] = date
        exif.get_ifd(IFD.Exif)[Base.OffsetTimeOriginal] = "+01:00"
        gps = exif.get_ifd(IFD.GPSInfo)
        gps[GPS.GPSLatitudeRef] = "N"
        gps[GPS.GPSLatitude] = (IFDRational(24), IFDRational(33), IFDRational(36))
        gps[GPS.GPSLongitudeRef] = "W"
        gps[GPS.GPSLongitude] = (IFDRational(81), IFDRational(48), IFDRational(27))
        img.save(str(folder.join(name)), format="JPEG", exif=exif)

    # The EXIF reader alone, which needs no ExifTool installed
    descs = run_process_for_descs(["--geotag_source=native", str(folder)])

    by_name = {Path(desc["filename"]).name: desc for desc in descs}
    assert by_name["placeholder.jpg"]["error"]["type"] == "MapillaryGeoTaggingError"
    assert by_name["valid.jpg"]["MAPCaptureTime"] == "2020_01_02_02_04_05_000"


def test_process_images_with_capture_times_outside_the_writable_range(
    tmpdir: py.path.local,
):
    """
    A capture time judged in UTC before 1970, or in year 10000, which no
    description can be written with: geotagged by a GPX, the latter stopped
    the run without a description
    """
    from PIL import Image
    from PIL.ExifTags import Base, IFD

    folder = tmpdir.mkdir("images")
    for name, date, offset in [
        ("valid.jpg", "2020:01:02 03:04:05", "+01:00"),
        ("before_1970_in_utc.jpg", "1970:01:01 00:30:00", "+02:00"),
        ("year_10000_in_utc.jpg", "9999:12:31 23:00:00", "-05:00"),
    ]:
        img = Image.new("RGB", (4, 4), (0, 0, 0))
        exif = img.getexif()
        exif.get_ifd(IFD.Exif)[Base.DateTimeOriginal] = date
        exif.get_ifd(IFD.Exif)[Base.OffsetTimeOriginal] = offset
        img.save(str(folder.join(name)), format="JPEG", exif=exif)
    gpx = tmpdir.join("track.gpx")
    gpx.write(
        '<?xml version="1.0"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        "<trk><trkseg>"
        '<trkpt lat="24.56" lon="-81.80"><time>2020-01-02T02:00:00Z</time></trkpt>'
        '<trkpt lat="24.57" lon="-81.81"><time>2020-01-02T02:10:00Z</time></trkpt>'
        "</trkseg></trk></gpx>"
    )

    descs = run_process_for_descs(
        ["--geotag_source=gpx", f"--geotag_source_path={gpx}", str(folder)]
    )

    by_name = {Path(desc["filename"]).name: desc for desc in descs}
    assert by_name["valid.jpg"]["MAPCaptureTime"] == "2020_01_02_02_04_05_000"
    for name, rejected in [
        ("before_1970_in_utc.jpg", "1970-01-01 00:30:00+02:00"),
        ("year_10000_in_utc.jpg", "9999-12-31 23:00:00-05:00"),
    ]:
        assert by_name[name]["error"] == {
            "type": "MapillaryGeoTaggingError",
            "message": f"Unable to extract timestamp from the image: invalid capture time {rejected}",
        }
