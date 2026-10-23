# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import json
import subprocess
from pathlib import Path

import py.path
import pytest
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor
from mapillary_tools.geotag.video_extractors.native import NativeVideoExtractor

from .fixtures import (
    assert_contains_image_descs,
    extract_all_uploaded_descs,
    run_process_and_upload_for_descs,
    run_process_for_descs,
    run_upload,
    setup_config,
    setup_data,
    setup_upload,
)


@pytest.mark.usefixtures("setup_config")
def test_upload_everything(setup_data: py.path.local, setup_upload: py.path.local):
    descs = run_process_and_upload_for_descs([str(setup_data)])

    uploaded_descs: list[dict] = sum(extract_all_uploaded_descs(Path(setup_upload)), [])
    assert len(uploaded_descs) > 0, "No data were uploaded"
    assert len([d for d in uploaded_descs if d["filetype"] == "camm"]) > 0
    assert len([d for d in uploaded_descs if d["filetype"] == "error"]) == 0
    assert len([d for d in uploaded_descs if d["filetype"] == "image"]) > 0

    # TODO: check video descs
    assert_contains_image_descs(descs, uploaded_descs)


@pytest.mark.usefixtures("setup_config")
def test_upload_video_with_gpx_running_past_both_ends(
    setup_data: py.path.local, setup_upload: py.path.local
):
    """
    The uploaded track keeps only the video, with a point interpolated at
    either end, from a GPX of a longer trip
    """
    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")
    duration = 12.137125
    points = NativeVideoExtractor(Path(video_path)).extract().points
    clock = GPXVideoExtractor._read_video_clock(points)
    assert clock is not None
    video_start = clock.to_unix_time(0)
    # From 12.5 seconds before the video to about 47 seconds after it
    trkpts = "".join(
        f'<trkpt lat="{37.0 + i * 0.0001:.7f}" lon="-122.0"><time>'
        f"{datetime.datetime.fromtimestamp(video_start - 12.5 + i, datetime.timezone.utc).isoformat()}"
        "</time></trkpt>"
        for i in range(61)
    )
    gpx_file = setup_data.join("track.gpx")
    gpx_file.write(
        '<?xml version="1.0"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{trkpts}</trkseg></trk></gpx>\n"
    )

    run_process_and_upload_for_descs(
        [
            *["--geotag_source", "gpx"],
            *["--geotag_source_path", str(gpx_file)],
            str(video_path),
        ]
    )

    [[desc]] = extract_all_uploaded_descs(Path(setup_upload))
    track = desc["MAPGPSTrack"]
    # The GPX points recorded from 0.5 to 11.5 seconds, and one at either end
    assert len(track) == 14
    first, last = track[0], track[-1]
    assert first[0] == 0
    assert first[2] == pytest.approx(37.0 + 12.5 * 0.0001, abs=1e-7)
    assert first[5] == pytest.approx(video_start, abs=1e-3)
    assert last[0] == pytest.approx(duration * 1000, abs=1)
    assert last[5] == pytest.approx(video_start + duration, abs=1e-3)


@pytest.mark.usefixtures("setup_config")
def test_upload_image_dir(setup_data: py.path.local, setup_upload: py.path.local):
    descs = run_process_and_upload_for_descs(["--file_types=image", str(setup_data)])

    uploaded_descs: list[dict] = sum(extract_all_uploaded_descs(Path(setup_upload)), [])
    assert len(uploaded_descs) > 0, "No images were uploaded"

    assert_contains_image_descs(descs, uploaded_descs)


@pytest.mark.usefixtures("setup_config")
def test_upload_image_dir_twice(setup_data: py.path.local, setup_upload: py.path.local):
    descs = run_process_for_descs([str(setup_data)])

    # first upload
    first_descs = run_process_and_upload_for_descs(
        ["--file_types=image", str(setup_data)]
    )
    assert len([d for d in first_descs if d["filetype"] == "image"]) > 0
    first_uploaded_descs = extract_all_uploaded_descs(Path(setup_upload))
    assert_contains_image_descs(descs, sum(first_uploaded_descs, []))

    # expect the second upload to not produce new uploads
    second_descs = run_process_and_upload_for_descs(
        [
            "--file_types=image",
            str(setup_data),
            str(setup_data),
            str(setup_data.join("images/DSC00001.JPG")),
        ]
    )
    assert len([d for d in second_descs if d["filetype"] == "image"]) > 0
    second_uploaded_descs = extract_all_uploaded_descs(Path(setup_upload))
    assert_contains_image_descs(descs, sum(second_uploaded_descs, []))


@pytest.mark.usefixtures("setup_config")
def test_upload_wrong_descs(setup_data: py.path.local, setup_upload: py.path.local):
    descs = run_process_for_descs([str(setup_data)])

    descs.append(
        {
            "filename": str(setup_data.join("not_found")),
            "filetype": "image",
            "MAPLatitude": 1,
            "MAPLongitude": 181,
            "MAPCaptureTime": "1970_01_01_00_00_02_000",
            "MAPCompassHeading": {"TrueHeading": 17.0, "MagneticHeading": 17.0},
        },
    )

    desc_path = setup_data.join("mapillary_image_description.json")

    with open(desc_path, "w") as fp:
        fp.write(json.dumps(descs))

    with pytest.raises(subprocess.CalledProcessError) as ex:
        run_upload(
            [
                *["--desc_path", str(desc_path)],
                str(setup_data),
                str(setup_data),
                str(setup_data.join("images/DSC00001.JPG")),
            ]
        )

    assert ex.value.returncode == 15, ex.value.stderr
