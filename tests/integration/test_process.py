# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import json
import os
import subprocess
from pathlib import Path

import gpxpy
import py.path
import pytest

from .fixtures import (
    assert_contains_image_descs,
    assert_descs_exact_equal,
    EXECUTABLE,
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
        assert desc["error"] == {
            "type": "MapillaryInvalidGPXError",
            "message": "test.gpx is not a valid GPX file. Replace it with a valid GPX file.",
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
    assert video_desc["error"] == {
        "type": "MapillaryInvalidGPXError",
        "message": (
            "max-360mode.gpx is not a valid GPX file. Replace it with a valid GPX file."
        ),
    }


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
