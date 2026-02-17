# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import xml.etree.ElementTree as ET

from mapillary_tools.exiftool_read_video import (
    _aggregate_gps_track,
    _aggregate_gps_track_by_sample_time,
    expand_tag,
)


def test_aggregate_gps_track_with_gps_time_tag():
    texts_by_tag = {
        expand_tag("QuickTime:GPSLongitude"): ["29.0", "29.1"],
        expand_tag("QuickTime:GPSLatitude"): ["36.7", "36.8"],
        expand_tag("QuickTime:GPSDateTime"): [
            "2025-01-01 00:00:00Z",
            "2025-01-01 00:00:01Z",
        ],
        expand_tag("QuickTime:GPSTimeStamp"): [
            "2025-01-01 00:00:10Z",
            "2025-01-01 00:00:11Z",
        ],
    }
    track = _aggregate_gps_track(
        texts_by_tag,
        time_tag="QuickTime:GPSDateTime",
        lon_tag="QuickTime:GPSLongitude",
        lat_tag="QuickTime:GPSLatitude",
        gps_time_tag="QuickTime:GPSTimeStamp",
    )
    assert len(track) == 2
    for point in track:
        assert point.epoch_time is not None


def test_aggregate_gps_track_gps_time_fallback_to_time_tag():
    texts_by_tag = {
        expand_tag("QuickTime:GPSLongitude"): ["29.0", "29.1"],
        expand_tag("QuickTime:GPSLatitude"): ["36.7", "36.8"],
        expand_tag("QuickTime:GPSDateTime"): [
            "2025-01-01 00:00:00Z",
            "2025-01-01 00:00:01Z",
        ],
    }
    track = _aggregate_gps_track(
        texts_by_tag,
        time_tag="QuickTime:GPSDateTime",
        lon_tag="QuickTime:GPSLongitude",
        lat_tag="QuickTime:GPSLatitude",
        gps_time_tag=None,
    )
    assert len(track) == 2
    # Without gps_time_tag, epoch_time should be populated from time_tag timestamps
    for point in track:
        assert point.epoch_time is not None


def test_aggregate_gps_track_no_time_tags():
    texts_by_tag = {
        expand_tag("QuickTime:GPSLongitude"): ["29.0", "29.1"],
        expand_tag("QuickTime:GPSLatitude"): ["36.7", "36.8"],
    }
    track = _aggregate_gps_track(
        texts_by_tag,
        time_tag=None,
        lon_tag="QuickTime:GPSLongitude",
        lat_tag="QuickTime:GPSLatitude",
        gps_time_tag=None,
    )
    assert len(track) == 2
    for point in track:
        assert point.epoch_time is None


def test_aggregate_gps_track_gps_time_length_mismatch():
    texts_by_tag = {
        expand_tag("QuickTime:GPSLongitude"): ["29.0", "29.1", "29.2"],
        expand_tag("QuickTime:GPSLatitude"): ["36.7", "36.8", "36.9"],
        expand_tag("QuickTime:GPSDateTime"): [
            "2025-01-01 00:00:00Z",
            "2025-01-01 00:00:01Z",
            "2025-01-01 00:00:02Z",
        ],
        # Mismatched length: only 2 entries for 3 coordinates
        expand_tag("QuickTime:GPSTimeStamp"): [
            "2025-01-01 00:00:10Z",
            "2025-01-01 00:00:11Z",
        ],
    }
    track = _aggregate_gps_track(
        texts_by_tag,
        time_tag="QuickTime:GPSDateTime",
        lon_tag="QuickTime:GPSLongitude",
        lat_tag="QuickTime:GPSLatitude",
        gps_time_tag="QuickTime:GPSTimeStamp",
    )
    assert len(track) == 3
    # Length mismatch triggers fallback: all epoch_time should be None
    for point in track:
        assert point.epoch_time is None


def _make_element(tag: str, text: str) -> ET.Element:
    el = ET.Element(expand_tag(tag))
    el.text = text
    return el


def test_aggregate_gps_track_by_sample_time_with_gps_time():
    track_ns = "Track1"
    elements = [
        _make_element(f"{track_ns}:GPSLongitude", "29.0"),
        _make_element(f"{track_ns}:GPSLatitude", "36.7"),
        _make_element(f"{track_ns}:GPSDateTime", "2025-01-01 00:00:00Z"),
        _make_element(f"{track_ns}:GPSLongitude", "29.1"),
        _make_element(f"{track_ns}:GPSLatitude", "36.8"),
        _make_element(f"{track_ns}:GPSDateTime", "2025-01-01 00:00:01Z"),
    ]
    sample_iterator = [(0.0, 2.0, elements)]
    track = _aggregate_gps_track_by_sample_time(
        sample_iterator,
        lon_tag=f"{track_ns}:GPSLongitude",
        lat_tag=f"{track_ns}:GPSLatitude",
        gps_time_tag=f"{track_ns}:GPSDateTime",
    )
    assert len(track) == 2
    for point in track:
        assert point.epoch_time is not None


def test_aggregate_gps_track_by_sample_time_no_gps_time():
    track_ns = "Track1"
    elements = [
        _make_element(f"{track_ns}:GPSLongitude", "29.0"),
        _make_element(f"{track_ns}:GPSLatitude", "36.7"),
        _make_element(f"{track_ns}:GPSLongitude", "29.1"),
        _make_element(f"{track_ns}:GPSLatitude", "36.8"),
    ]
    sample_iterator = [(0.0, 2.0, elements)]
    track = _aggregate_gps_track_by_sample_time(
        sample_iterator,
        lon_tag=f"{track_ns}:GPSLongitude",
        lat_tag=f"{track_ns}:GPSLatitude",
        gps_time_tag=None,
    )
    assert len(track) == 2
    for point in track:
        assert point.epoch_time is None
