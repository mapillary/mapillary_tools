# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
A GPX file that geotags several videos, or the samples of a video and then
their images, is parsed once in a run, and warned about once
"""

from __future__ import annotations

import logging
import multiprocessing
from pathlib import Path

import gpxpy
import pytest

from mapillary_tools import sample_video
from mapillary_tools.geotag import (
    geotag_images_from_gpx_file,
    geotag_videos_from_gpx,
    utils,
)
from mapillary_tools.geotag.options import SourceOption, SourcePathOption, SourceType
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor


def _gpx(*segments: list[tuple[str, float]]) -> bytes:
    """A GPX file of a track with **segments** of (time, latitude) points"""
    trksegs = "".join(
        "<trkseg>"
        + "".join(
            f'<trkpt lat="{lat}" lon="13.0"><time>{time}</time></trkpt>'
            for time, lat in segment
        )
        + "</trkseg>"
        for segment in segments
    )
    return (
        '<?xml version="1.0"?>'
        '<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk>{trksegs}</trk></gpx>"
    ).encode("utf-8")


ONE_TRACK = _gpx([("2025-01-01T00:00:00Z", 52.0), ("2025-01-01T00:00:01Z", 52.1)])
TWO_TRACKS = _gpx(
    [("2025-01-01T00:00:00Z", 52.0), ("2025-01-01T00:00:01Z", 52.1)],
    [("2025-01-01T00:00:02Z", 52.2), ("2025-01-01T00:00:03Z", 52.3)],
)


@pytest.fixture
def parses(monkeypatch) -> list[int]:
    """Counts the GPX files parsed, with nothing parsed or warned of before"""
    if hasattr(utils, "_PARSED_GPX"):
        monkeypatch.setattr(utils, "_PARSED_GPX", type(utils._PARSED_GPX)())
    if hasattr(utils, "_WARNED"):
        monkeypatch.setattr(utils, "_WARNED", set())
    parsed: list[int] = []
    parse = gpxpy.parse

    def counting_parse(*args, **kwargs):
        parsed.append(1)
        return parse(*args, **kwargs)

    monkeypatch.setattr(gpxpy, "parse", counting_parse)
    return parsed


def test_a_gpx_file_is_parsed_once(tmp_path: Path, parses: list[int]):
    gpx = tmp_path / "track.gpx"
    gpx.write_bytes(ONE_TRACK)

    first = utils.parse_gpx(gpx)
    second = utils.parse_gpx(gpx)

    assert len(parses) == 1
    assert first == second
    # Copies, which the caller may change
    first[0][0].time = 0
    assert utils.parse_gpx(gpx)[0][0].time != 0


def test_a_changed_gpx_file_is_parsed_again(tmp_path: Path, parses: list[int]):
    gpx = tmp_path / "track.gpx"
    gpx.write_bytes(ONE_TRACK)
    assert len(utils.parse_gpx(gpx)) == 1

    gpx.write_bytes(TWO_TRACKS)
    assert len(utils.parse_gpx(gpx)) == 2
    assert len(parses) == 2


def test_only_the_last_gpx_files_are_kept(tmp_path: Path, parses: list[int]):
    paths = []
    for idx in range(utils._MAX_PARSED_GPX + 1):
        gpx = tmp_path / f"track{idx}.gpx"
        gpx.write_bytes(ONE_TRACK)
        paths.append(gpx)
        utils.read_gpx_tracks(gpx)

    assert len(utils._PARSED_GPX) == utils._MAX_PARSED_GPX
    assert not utils.was_gpx_read(paths[0])
    assert utils.was_gpx_read(paths[-1])


def test_a_worker_of_a_pool_keeps_no_gpx_file(
    tmp_path: Path, parses: list[int], monkeypatch
):
    """It parses the GPX file of one video only, and would keep it until it exits"""
    gpx = tmp_path / "track.gpx"
    gpx.write_bytes(ONE_TRACK)
    monkeypatch.setattr(multiprocessing, "parent_process", lambda: object())

    assert len(utils.read_gpx_tracks(gpx)) == 1
    assert not utils.was_gpx_read(gpx)


def test_an_invalid_gpx_file_is_parsed_once(tmp_path: Path, parses: list[int]):
    gpx = tmp_path / "track.gpx"
    gpx.write_bytes(b"not a GPX file")

    for _ in range(2):
        with pytest.raises(Exception):
            utils.read_gpx_tracks(gpx)
    assert len(parses) == 1


def test_images_warn_of_the_tracks_once(tmp_path: Path, parses: list[int], caplog):
    gpx = tmp_path / "track.gpx"
    gpx.write_bytes(TWO_TRACKS)

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            points = geotag_images_from_gpx_file._read_gpx_points(gpx)

    assert len(points) == 4
    assert len(parses) == 1
    assert caplog.text.count("Found 2 tracks in the GPX file") == 1


def test_videos_warn_of_the_tracks_once(tmp_path: Path, parses: list[int], caplog):
    gpx = tmp_path / "track.gpx"
    gpx.write_bytes(TWO_TRACKS)

    with caplog.at_level(logging.WARNING):
        geotag_images_from_gpx_file._read_gpx_points(gpx)
        for name in ("a.mp4", "b.mp4"):
            points = GPXVideoExtractor(tmp_path / name, gpx)._read_gpx_points()

    assert len(points) == 4
    assert len(parses) == 1
    assert caplog.text.count("Found 2 tracks") == 1


def test_video_points_are_copies(tmp_path: Path, parses: list[int]):
    """GPX sync moves the points of a track to the video"""
    gpx = tmp_path / "track.gpx"
    gpx.write_bytes(ONE_TRACK)

    points = GPXVideoExtractor(tmp_path / "a.mp4", gpx)._read_gpx_points()
    for point in points:
        point.time = 0

    assert [p.time for p in utils.parse_gpx(gpx)[0]] == [
        1735689600.0,
        1735689601.0,
    ]


def test_a_gpx_file_of_several_videos_is_read_before_the_pool(
    tmp_path: Path, parses: list[int]
):
    shared = tmp_path / "shared.gpx"
    shared.write_bytes(ONE_TRACK)
    own = tmp_path / "c.gpx"
    own.write_bytes(TWO_TRACKS)
    videos = []
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        videos.append(tmp_path / name)
        videos[-1].write_bytes(b"")

    shared_geotag = geotag_videos_from_gpx.GeotagVideosFromGPX(
        source_path=SourcePathOption(source_path=shared)
    )
    extractors = shared_geotag._generate_video_extractors(videos)
    assert all(
        isinstance(e, GPXVideoExtractor) and e._tracks is not None for e in extractors
    )
    assert len(parses) == 1

    # A GPX file of each video is left to the pool
    own_geotag = geotag_videos_from_gpx.GeotagVideosFromGPX(
        source_path=SourcePathOption(pattern="%g.gpx")
    )
    (extractor,) = own_geotag._generate_video_extractors(videos[2:])
    assert isinstance(extractor, GPXVideoExtractor)
    assert extractor._tracks is None

    # Unless this process parsed it already
    utils.read_gpx_tracks(own)
    (extractor,) = own_geotag._generate_video_extractors(videos[2:])
    assert isinstance(extractor, GPXVideoExtractor)
    assert extractor._tracks is not None
    assert len(parses) == 2


def test_interval_samples_read_the_gpx_file_once(tmp_path: Path, parses: list[int]):
    gpx = tmp_path / "track.gpx"
    gpx.write_bytes(ONE_TRACK)
    sources = [
        SourceOption(SourceType.GPX, source_path=SourcePathOption(source_path=gpx))
    ]

    for _ in range(3):
        track = sample_video._read_file_track_for_interval_samples(sources)
        assert track is not None

    assert len(parses) == 1


def test_distance_sampling_reads_the_video_in_this_process(tmp_path: Path, monkeypatch):
    """So that a GPX file that geotags several videos is parsed once"""
    calls = []

    def process(paths, options, filetypes=None):
        calls.append([option.num_processes for option in options])
        raise RuntimeError("stop here")

    monkeypatch.setattr(sample_video.factory, "process", process)
    monkeypatch.setattr(sample_video, "_probe_video", lambda ffmpeg, path: None)

    with pytest.raises(RuntimeError, match="stop here"):
        sample_video._sample_single_video_by_distance(
            tmp_path / "a.mp4",
            tmp_path / "samples",
            sample_distance=3,
            geotag_options=[SourceOption(SourceType.NATIVE)],
        )
    assert calls == [[0]]
