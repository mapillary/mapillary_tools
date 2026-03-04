# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from mapillary_tools.exiftool_read_video import (
    _aggregate_gps_track,
    _aggregate_gps_track_by_sample_time,
    _aggregate_samples,
    _deduplicate_gps_points,
    _extract_alternative_fields,
    _index_text_by_tag,
    _same_gps_point,
    ExifToolReadVideo,
    expand_tag,
)
from mapillary_tools.telemetry import GPSFix, GPSPoint


# ---------------------------------------------------------------------------
# Helper: build an ElementTree from raw XML strings
# ---------------------------------------------------------------------------


def _etree_from_xml(xml_str: str) -> ET.ElementTree:
    """Parse XML and return an ElementTree rooted at rdf:Description.

    In production, ExifToolReadVideo receives an ElementTree whose root is the
    rdf:Description element (not the enclosing rdf:RDF). This helper mimics
    that behaviour: it parses the full XML, finds the first rdf:Description
    child, and wraps it in an ElementTree.
    """
    rdf_root = ET.fromstring(xml_str)
    rdf_ns = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    desc = rdf_root.find(f"{{{rdf_ns}}}Description")
    if desc is None:
        raise ValueError("No rdf:Description found in the XML")
    return ET.ElementTree(desc)


def _make_element(tag: str, text: str) -> ET.Element:
    el = ET.Element(expand_tag(tag))
    el.text = text
    return el


# ---------------------------------------------------------------------------
# Real-world-style XML fixtures
# ---------------------------------------------------------------------------

BLACKVUE_XML = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:QuickTime='http://ns.exiftool.org/QuickTime/QuickTime/1.0/'
 xmlns:IFD0='http://ns.exiftool.org/EXIF/IFD0/1.0/'
 xmlns:UserData='http://ns.exiftool.org/QuickTime/UserData/1.0/'>
 <IFD0:Make>BlackVue</IFD0:Make>
 <IFD0:Model>DR900S-2CH</IFD0:Model>
 <UserData:SerialNumber>BV900S123456</UserData:SerialNumber>
 <QuickTime:GPSDateTime>2019:09:02 10:23:28.00Z</QuickTime:GPSDateTime>
 <QuickTime:GPSLatitude>37.265547</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>28.213497</QuickTime:GPSLongitude>
 <QuickTime:GPSSpeed>52.7561</QuickTime:GPSSpeed>
 <QuickTime:GPSTrack>133.46</QuickTime:GPSTrack>
 <QuickTime:GPSAltitude>402.9</QuickTime:GPSAltitude>
 <QuickTime:GPSDateTime>2019:09:02 10:23:29.00Z</QuickTime:GPSDateTime>
 <QuickTime:GPSLatitude>37.265461</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>28.213611</QuickTime:GPSLongitude>
 <QuickTime:GPSSpeed>50.0466</QuickTime:GPSSpeed>
 <QuickTime:GPSTrack>133.11</QuickTime:GPSTrack>
 <QuickTime:GPSAltitude>402.8</QuickTime:GPSAltitude>
 <QuickTime:GPSDateTime>2019:09:02 10:23:30.00Z</QuickTime:GPSDateTime>
 <QuickTime:GPSLatitude>37.265378</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>28.213722</QuickTime:GPSLongitude>
 <QuickTime:GPSSpeed>47.6205</QuickTime:GPSSpeed>
 <QuickTime:GPSTrack>132.83</QuickTime:GPSTrack>
 <QuickTime:GPSAltitude>402.8</QuickTime:GPSAltitude>
</rdf:Description>
</rdf:RDF>
"""

# GoPro Track-based GPS (Track namespace).
# Note: SampleTime/SampleDuration are plain floats (exiftool XML numeric output).
GOPRO_XML = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.360'
 xmlns:Track1='http://ns.exiftool.org/QuickTime/Track1/1.0/'
 xmlns:GoPro='http://ns.exiftool.org/QuickTime/GoPro/1.0/'>
 <GoPro:Make>GoPro</GoPro:Make>
 <GoPro:Model>GoPro Max</GoPro:Model>
 <GoPro:SerialNumber>C3456789012345</GoPro:SerialNumber>
 <Track1:SampleTime>0</Track1:SampleTime>
 <Track1:SampleDuration>1.001</Track1:SampleDuration>
 <Track1:GPSLatitude>47.359832</Track1:GPSLatitude>
 <Track1:GPSLongitude>8.522706</Track1:GPSLongitude>
 <Track1:GPSAltitude>414.9</Track1:GPSAltitude>
 <Track1:GPSDateTime>2022:07:31 00:25:23.200Z</Track1:GPSDateTime>
 <Track1:GPSSpeed>5.376</Track1:GPSSpeed>
 <Track1:GPSTrack>167.58</Track1:GPSTrack>
 <Track1:GPSMeasureMode>3</Track1:GPSMeasureMode>
 <Track1:GPSHPositioningError>2.19</Track1:GPSHPositioningError>
 <Track1:SampleTime>1.001</Track1:SampleTime>
 <Track1:SampleDuration>1.001</Track1:SampleDuration>
 <Track1:GPSLatitude>47.359810</Track1:GPSLatitude>
 <Track1:GPSLongitude>8.522680</Track1:GPSLongitude>
 <Track1:GPSAltitude>415.2</Track1:GPSAltitude>
 <Track1:GPSDateTime>2022:07:31 00:25:24.200Z</Track1:GPSDateTime>
 <Track1:GPSSpeed>4.992</Track1:GPSSpeed>
 <Track1:GPSTrack>168.23</Track1:GPSTrack>
 <Track1:GPSMeasureMode>3</Track1:GPSMeasureMode>
 <Track1:GPSHPositioningError>2.15</Track1:GPSHPositioningError>
</rdf:Description>
</rdf:RDF>
"""

INSTA360_XML = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:Insta360='http://ns.exiftool.org/Trailer/Insta360/1.0/'>
 <Insta360:Make>Insta360</Insta360:Make>
 <Insta360:Model>Insta360 X3</Insta360:Model>
 <Insta360:SerialNumber>ISN12345678</Insta360:SerialNumber>
 <Insta360:GPSDateTime>2023:09:23 15:13:34.00Z</Insta360:GPSDateTime>
 <Insta360:GPSLatitude>47.371</Insta360:GPSLatitude>
 <Insta360:GPSLongitude>8.542</Insta360:GPSLongitude>
 <Insta360:GPSAltitude>408.5</Insta360:GPSAltitude>
 <Insta360:GPSDateTime>2023:09:23 15:13:35.00Z</Insta360:GPSDateTime>
 <Insta360:GPSLatitude>47.372</Insta360:GPSLatitude>
 <Insta360:GPSLongitude>8.543</Insta360:GPSLongitude>
 <Insta360:GPSAltitude>409.1</Insta360:GPSAltitude>
</rdf:Description>
</rdf:RDF>
"""


# ---------------------------------------------------------------------------
# _index_text_by_tag
# ---------------------------------------------------------------------------


class TestIndexTextByTag:
    def test_basic_indexing(self):
        elements = [
            _make_element("QuickTime:GPSLatitude", "37.0"),
            _make_element("QuickTime:GPSLongitude", "28.0"),
            _make_element("QuickTime:GPSLatitude", "38.0"),
        ]
        result = _index_text_by_tag(elements)
        lat_tag = expand_tag("QuickTime:GPSLatitude")
        lon_tag = expand_tag("QuickTime:GPSLongitude")
        assert result[lat_tag] == ["37.0", "38.0"]
        assert result[lon_tag] == ["28.0"]

    def test_empty_elements(self):
        result = _index_text_by_tag([])
        assert result == {}

    def test_element_with_no_text_is_skipped(self):
        el = ET.Element(expand_tag("QuickTime:GPSLatitude"))
        # el.text is None by default
        result = _index_text_by_tag([el])
        assert result == {}

    def test_mixed_text_and_none(self):
        el1 = _make_element("QuickTime:GPSLatitude", "37.0")
        el2 = ET.Element(expand_tag("QuickTime:GPSLatitude"))
        el3 = _make_element("QuickTime:GPSLatitude", "38.0")
        result = _index_text_by_tag([el1, el2, el3])
        lat_tag = expand_tag("QuickTime:GPSLatitude")
        # Only elements with text are included
        assert result[lat_tag] == ["37.0", "38.0"]


# ---------------------------------------------------------------------------
# _extract_alternative_fields
# ---------------------------------------------------------------------------


class TestExtractAlternativeFields:
    def test_extract_float_value(self):
        texts = {expand_tag("QuickTime:GPSLatitude"): ["37.265547"]}
        result = _extract_alternative_fields(texts, ["QuickTime:GPSLatitude"], float)
        assert result == pytest.approx(37.265547)

    def test_extract_int_value(self):
        texts = {expand_tag("Track1:GPSMeasureMode"): ["3"]}
        result = _extract_alternative_fields(texts, ["Track1:GPSMeasureMode"], int)
        assert result == 3

    def test_extract_str_value(self):
        texts = {expand_tag("IFD0:Make"): ["BlackVue"]}
        result = _extract_alternative_fields(texts, ["IFD0:Make"], str)
        assert result == "BlackVue"

    def test_extract_list_value(self):
        texts = {expand_tag("QuickTime:GPSLatitude"): ["37.0", "38.0"]}
        result = _extract_alternative_fields(texts, ["QuickTime:GPSLatitude"], list)
        assert result == ["37.0", "38.0"]

    def test_returns_none_for_missing_field(self):
        texts = {expand_tag("QuickTime:GPSLatitude"): ["37.0"]}
        result = _extract_alternative_fields(texts, ["QuickTime:GPSLongitude"], float)
        assert result is None

    def test_alternative_fallback(self):
        """First field is missing, second is present."""
        texts = {expand_tag("UserData:Make"): ["TestMake"]}
        result = _extract_alternative_fields(texts, ["IFD0:Make", "UserData:Make"], str)
        assert result == "TestMake"

    def test_first_alternative_preferred(self):
        """When both fields are present, first is used."""
        texts = {
            expand_tag("IFD0:Make"): ["First"],
            expand_tag("UserData:Make"): ["Second"],
        }
        result = _extract_alternative_fields(texts, ["IFD0:Make", "UserData:Make"], str)
        assert result == "First"

    def test_invalid_float_returns_none(self):
        texts = {expand_tag("QuickTime:GPSLatitude"): ["not_a_number"]}
        result = _extract_alternative_fields(texts, ["QuickTime:GPSLatitude"], float)
        assert result is None

    def test_invalid_int_returns_none(self):
        texts = {expand_tag("Track1:GPSMeasureMode"): ["abc"]}
        result = _extract_alternative_fields(texts, ["Track1:GPSMeasureMode"], int)
        assert result is None

    def test_all_fields_missing_returns_none(self):
        result = _extract_alternative_fields({}, ["IFD0:Make", "UserData:Make"], str)
        assert result is None

    def test_invalid_field_type_raises(self):
        texts = {expand_tag("IFD0:Make"): ["val"]}
        with pytest.raises(ValueError, match="Invalid field type"):
            _extract_alternative_fields(texts, ["IFD0:Make"], dict)  # type: ignore


# ---------------------------------------------------------------------------
# _same_gps_point and _deduplicate_gps_points
# ---------------------------------------------------------------------------


class TestSameGpsPoint:
    def _make_point(self, **overrides) -> GPSPoint:
        defaults = dict(
            time=0.0,
            lat=37.0,
            lon=28.0,
            alt=400.0,
            angle=133.0,
            epoch_time=None,
            fix=None,
            precision=None,
            ground_speed=None,
        )
        defaults.update(overrides)
        return GPSPoint(**defaults)

    def test_identical_points_are_same(self):
        p = self._make_point()
        assert _same_gps_point(p, p) is True

    def test_different_alt_are_same(self):
        """Altitude does not affect sameness."""
        p1 = self._make_point(alt=400.0)
        p2 = self._make_point(alt=500.0)
        assert _same_gps_point(p1, p2) is True

    def test_different_lat_are_not_same(self):
        p1 = self._make_point(lat=37.0)
        p2 = self._make_point(lat=38.0)
        assert _same_gps_point(p1, p2) is False

    def test_different_lon_are_not_same(self):
        p1 = self._make_point(lon=28.0)
        p2 = self._make_point(lon=29.0)
        assert _same_gps_point(p1, p2) is False

    def test_different_time_are_not_same(self):
        p1 = self._make_point(time=0.0)
        p2 = self._make_point(time=1.0)
        assert _same_gps_point(p1, p2) is False

    def test_different_angle_are_not_same(self):
        p1 = self._make_point(angle=100.0)
        p2 = self._make_point(angle=200.0)
        assert _same_gps_point(p1, p2) is False

    def test_different_epoch_time_are_not_same(self):
        p1 = self._make_point(epoch_time=1000.0)
        p2 = self._make_point(epoch_time=2000.0)
        assert _same_gps_point(p1, p2) is False

    def test_different_ground_speed_are_same(self):
        """ground_speed is not checked by _same_gps_point."""
        p1 = self._make_point(ground_speed=10.0)
        p2 = self._make_point(ground_speed=50.0)
        assert _same_gps_point(p1, p2) is True


class TestDeduplicateGpsPoints:
    def _make_point(self, **overrides) -> GPSPoint:
        defaults = dict(
            time=0.0,
            lat=37.0,
            lon=28.0,
            alt=400.0,
            angle=133.0,
            epoch_time=None,
            fix=None,
            precision=None,
            ground_speed=None,
        )
        defaults.update(overrides)
        return GPSPoint(**defaults)

    def test_empty_track(self):
        assert _deduplicate_gps_points([], _same_gps_point) == []

    def test_no_duplicates(self):
        track = [
            self._make_point(time=0.0, lat=37.0),
            self._make_point(time=1.0, lat=37.1),
        ]
        result = _deduplicate_gps_points(track, _same_gps_point)
        assert len(result) == 2

    def test_consecutive_duplicates_removed(self):
        p = self._make_point(time=0.0, lat=37.0)
        track = [p, p, p]
        result = _deduplicate_gps_points(track, _same_gps_point)
        assert len(result) == 1

    def test_non_consecutive_duplicates_kept(self):
        p1 = self._make_point(time=0.0, lat=37.0)
        p2 = self._make_point(time=1.0, lat=38.0)
        p3 = self._make_point(time=0.0, lat=37.0)  # same as p1 but not consecutive
        track = [p1, p2, p3]
        result = _deduplicate_gps_points(track, _same_gps_point)
        assert len(result) == 3

    def test_only_alt_differs_is_duplicate(self):
        """Points differing only by altitude are considered same."""
        p1 = self._make_point(alt=400.0)
        p2 = self._make_point(alt=500.0)
        result = _deduplicate_gps_points([p1, p2], _same_gps_point)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _aggregate_gps_track
# ---------------------------------------------------------------------------


class TestAggregateGpsTrack:
    def test_basic_quicktime_track(self):
        texts = {
            expand_tag("QuickTime:GPSLongitude"): [
                "28.213497",
                "28.213611",
                "28.213722",
            ],
            expand_tag("QuickTime:GPSLatitude"): [
                "37.265547",
                "37.265461",
                "37.265378",
            ],
            expand_tag("QuickTime:GPSDateTime"): [
                "2019:09:02 10:23:28.00Z",
                "2019:09:02 10:23:29.00Z",
                "2019:09:02 10:23:30.00Z",
            ],
            expand_tag("QuickTime:GPSAltitude"): ["402.9", "402.8", "402.8"],
            expand_tag("QuickTime:GPSTrack"): ["133.46", "133.11", "132.83"],
        }
        track = _aggregate_gps_track(
            texts,
            time_tag="QuickTime:GPSDateTime",
            lon_tag="QuickTime:GPSLongitude",
            lat_tag="QuickTime:GPSLatitude",
            alt_tag="QuickTime:GPSAltitude",
            direction_tag="QuickTime:GPSTrack",
            gps_time_tag="QuickTime:GPSDateTime",
        )
        assert len(track) == 3
        # Times should be normalized relative to first point
        assert track[0].time == pytest.approx(0.0)
        assert track[1].time == pytest.approx(1.0)
        assert track[2].time == pytest.approx(2.0)
        # Check coordinates
        assert track[0].lat == pytest.approx(37.265547)
        assert track[0].lon == pytest.approx(28.213497)
        assert track[0].alt == pytest.approx(402.9)
        assert track[0].angle == pytest.approx(133.46)
        # epoch_time should be set from gps_time_tag
        for p in track:
            assert p.epoch_time is not None

    def test_mismatched_lon_lat_returns_empty(self):
        texts = {
            expand_tag("QuickTime:GPSLongitude"): ["28.0", "29.0"],
            expand_tag("QuickTime:GPSLatitude"): ["37.0"],
        }
        track = _aggregate_gps_track(
            texts,
            time_tag=None,
            lon_tag="QuickTime:GPSLongitude",
            lat_tag="QuickTime:GPSLatitude",
        )
        assert track == []

    def test_mismatched_timestamps_returns_empty(self):
        texts = {
            expand_tag("QuickTime:GPSLongitude"): ["28.0", "29.0"],
            expand_tag("QuickTime:GPSLatitude"): ["37.0", "38.0"],
            expand_tag("QuickTime:GPSDateTime"): [
                "2019:09:02 10:23:28.00Z",
            ],
        }
        track = _aggregate_gps_track(
            texts,
            time_tag="QuickTime:GPSDateTime",
            lon_tag="QuickTime:GPSLongitude",
            lat_tag="QuickTime:GPSLatitude",
        )
        assert track == []

    def test_no_time_tag_uses_zero(self):
        texts = {
            expand_tag("QuickTime:GPSLongitude"): ["28.0", "29.0"],
            expand_tag("QuickTime:GPSLatitude"): ["37.0", "38.0"],
        }
        track = _aggregate_gps_track(
            texts,
            time_tag=None,
            lon_tag="QuickTime:GPSLongitude",
            lat_tag="QuickTime:GPSLatitude",
        )
        # Without time_tag, all times are 0.0 but points differ in lat/lon
        # Deduplication checks time+lat+lon so both should remain
        assert len(track) == 2
        for p in track:
            assert p.time == 0.0
            assert p.epoch_time is None

    def test_empty_track(self):
        track = _aggregate_gps_track(
            {},
            time_tag=None,
            lon_tag="QuickTime:GPSLongitude",
            lat_tag="QuickTime:GPSLatitude",
        )
        assert track == []

    def test_none_lon_lat_values_skipped(self):
        """If a value cannot be parsed as float, it is skipped."""
        texts = {
            expand_tag("QuickTime:GPSLongitude"): ["28.0", "invalid"],
            expand_tag("QuickTime:GPSLatitude"): ["37.0", "38.0"],
            expand_tag("QuickTime:GPSDateTime"): [
                "2019:09:02 10:00:00Z",
                "2019:09:02 10:00:01Z",
            ],
        }
        track = _aggregate_gps_track(
            texts,
            time_tag="QuickTime:GPSDateTime",
            lon_tag="QuickTime:GPSLongitude",
            lat_tag="QuickTime:GPSLatitude",
        )
        # Second point has invalid lon so it gets skipped
        assert len(track) == 1

    def test_altitude_and_direction_shorter_padded_with_none(self):
        """Optional arrays shorter than coord arrays are padded with None."""
        texts = {
            expand_tag("QuickTime:GPSLongitude"): ["28.0", "29.0"],
            expand_tag("QuickTime:GPSLatitude"): ["37.0", "38.0"],
            expand_tag("QuickTime:GPSAltitude"): ["400.0"],  # only 1 for 2 coords
        }
        track = _aggregate_gps_track(
            texts,
            time_tag=None,
            lon_tag="QuickTime:GPSLongitude",
            lat_tag="QuickTime:GPSLatitude",
            alt_tag="QuickTime:GPSAltitude",
        )
        assert len(track) == 2
        assert track[0].alt == pytest.approx(400.0)
        assert track[1].alt is None

    def test_ground_speed_tag(self):
        texts = {
            expand_tag("QuickTime:GPSLongitude"): ["28.0"],
            expand_tag("QuickTime:GPSLatitude"): ["37.0"],
            expand_tag("QuickTime:GPSSpeed"): ["52.7561"],
        }
        track = _aggregate_gps_track(
            texts,
            time_tag=None,
            lon_tag="QuickTime:GPSLongitude",
            lat_tag="QuickTime:GPSLatitude",
            ground_speed_tag="QuickTime:GPSSpeed",
        )
        assert len(track) == 1
        assert track[0].ground_speed == pytest.approx(52.7561)

    def test_gps_time_tag_length_mismatch_falls_back_to_none(self):
        texts = {
            expand_tag("QuickTime:GPSLongitude"): ["28.0", "29.0"],
            expand_tag("QuickTime:GPSLatitude"): ["37.0", "38.0"],
            expand_tag("QuickTime:GPSDateTime"): [
                "2019:09:02 10:00:00Z",
                "2019:09:02 10:00:01Z",
            ],
            expand_tag("QuickTime:GPSTimeStamp"): [
                "2019:09:02 10:00:10Z",
            ],
        }
        track = _aggregate_gps_track(
            texts,
            time_tag="QuickTime:GPSDateTime",
            lon_tag="QuickTime:GPSLongitude",
            lat_tag="QuickTime:GPSLatitude",
            gps_time_tag="QuickTime:GPSTimeStamp",
        )
        assert len(track) == 2
        # Mismatch in gps_time_tag length: epoch_time falls back to None
        for p in track:
            assert p.epoch_time is None

    def test_track_is_sorted_by_time(self):
        """Points with out-of-order timestamps are sorted."""
        texts = {
            expand_tag("QuickTime:GPSLongitude"): ["28.0", "29.0"],
            expand_tag("QuickTime:GPSLatitude"): ["37.0", "38.0"],
            expand_tag("QuickTime:GPSDateTime"): [
                "2019:09:02 10:00:02Z",
                "2019:09:02 10:00:00Z",
            ],
        }
        track = _aggregate_gps_track(
            texts,
            time_tag="QuickTime:GPSDateTime",
            lon_tag="QuickTime:GPSLongitude",
            lat_tag="QuickTime:GPSLatitude",
        )
        assert len(track) == 2
        assert track[0].time < track[1].time


# ---------------------------------------------------------------------------
# _aggregate_samples
# ---------------------------------------------------------------------------


class TestAggregateSamples:
    def test_basic_two_samples(self):
        elements = [
            _make_element("Track1:SampleTime", "0"),
            _make_element("Track1:SampleDuration", "1.001"),
            _make_element("Track1:GPSLatitude", "47.0"),
            _make_element("Track1:GPSLongitude", "8.0"),
            _make_element("Track1:SampleTime", "1.001"),
            _make_element("Track1:SampleDuration", "1.001"),
            _make_element("Track1:GPSLatitude", "47.1"),
            _make_element("Track1:GPSLongitude", "8.1"),
        ]
        samples = list(
            _aggregate_samples(elements, "Track1:SampleTime", "Track1:SampleDuration")
        )
        assert len(samples) == 2
        # First sample
        sample_time, sample_dur, elems = samples[0]
        assert sample_time == pytest.approx(0.0)
        assert sample_dur == pytest.approx(1.001)
        # Elements are GPS data without SampleTime/SampleDuration
        assert len(elems) == 2
        # Second sample
        sample_time2, sample_dur2, elems2 = samples[1]
        assert sample_time2 == pytest.approx(1.001)
        assert sample_dur2 == pytest.approx(1.001)
        assert len(elems2) == 2

    def test_empty_elements(self):
        samples = list(
            _aggregate_samples([], "Track1:SampleTime", "Track1:SampleDuration")
        )
        assert samples == []

    def test_sample_time_none_skips_sample(self):
        """If sample time cannot be parsed as float, the sample is skipped."""
        elements = [
            _make_element("Track1:SampleTime", "not_a_number"),
            _make_element("Track1:SampleDuration", "1.0"),
            _make_element("Track1:GPSLatitude", "47.0"),
        ]
        samples = list(
            _aggregate_samples(elements, "Track1:SampleTime", "Track1:SampleDuration")
        )
        # sample_time is None so the last yield won't happen for that group
        assert len(samples) == 0

    def test_missing_duration_skips_sample(self):
        """If SampleDuration is missing, sample is not yielded."""
        elements = [
            _make_element("Track1:SampleTime", "0"),
            # No SampleDuration element
            _make_element("Track1:GPSLatitude", "47.0"),
        ]
        samples = list(
            _aggregate_samples(elements, "Track1:SampleTime", "Track1:SampleDuration")
        )
        # sample_duration is None, so the sample is skipped
        assert len(samples) == 0

    def test_last_sample_is_yielded(self):
        """The final sample (not followed by another SampleTime) is also yielded."""
        elements = [
            _make_element("Track1:SampleTime", "0"),
            _make_element("Track1:SampleDuration", "2.0"),
            _make_element("Track1:GPSLatitude", "47.0"),
        ]
        samples = list(
            _aggregate_samples(elements, "Track1:SampleTime", "Track1:SampleDuration")
        )
        assert len(samples) == 1
        sample_time, sample_dur, elems = samples[0]
        assert sample_time == pytest.approx(0.0)
        assert sample_dur == pytest.approx(2.0)
        assert len(elems) == 1


# ---------------------------------------------------------------------------
# _aggregate_gps_track_by_sample_time
# ---------------------------------------------------------------------------


class TestAggregateGpsTrackBySampleTime:
    def test_basic_sample_aggregation(self):
        track_ns = "Track1"
        elements = [
            _make_element(f"{track_ns}:GPSLongitude", "8.522706"),
            _make_element(f"{track_ns}:GPSLatitude", "47.359832"),
            _make_element(f"{track_ns}:GPSAltitude", "414.9"),
            _make_element(f"{track_ns}:GPSDateTime", "2022:07:31 00:25:23.200Z"),
            _make_element(f"{track_ns}:GPSSpeed", "5.376"),
            _make_element(f"{track_ns}:GPSTrack", "167.58"),
        ]
        sample_iterator = [(0.0, 1.001, elements)]
        track = _aggregate_gps_track_by_sample_time(
            sample_iterator,
            lon_tag=f"{track_ns}:GPSLongitude",
            lat_tag=f"{track_ns}:GPSLatitude",
            alt_tag=f"{track_ns}:GPSAltitude",
            gps_time_tag=f"{track_ns}:GPSDateTime",
            direction_tag=f"{track_ns}:GPSTrack",
            ground_speed_tag=f"{track_ns}:GPSSpeed",
        )
        assert len(track) == 1
        assert track[0].lat == pytest.approx(47.359832)
        assert track[0].lon == pytest.approx(8.522706)
        assert track[0].alt == pytest.approx(414.9)
        assert track[0].ground_speed == pytest.approx(5.376)
        assert track[0].angle == pytest.approx(167.58)

    def test_gps_fix_from_measure_mode(self):
        track_ns = "Track1"
        elements = [
            _make_element(f"{track_ns}:GPSLongitude", "8.0"),
            _make_element(f"{track_ns}:GPSLatitude", "47.0"),
            _make_element(f"{track_ns}:GPSMeasureMode", "3"),
        ]
        sample_iterator = [(0.0, 1.0, elements)]
        track = _aggregate_gps_track_by_sample_time(
            sample_iterator,
            lon_tag=f"{track_ns}:GPSLongitude",
            lat_tag=f"{track_ns}:GPSLatitude",
            gps_fix_tag=f"{track_ns}:GPSMeasureMode",
        )
        assert len(track) == 1
        assert track[0].fix == GPSFix.FIX_3D

    def test_gps_fix_2d(self):
        track_ns = "Track1"
        elements = [
            _make_element(f"{track_ns}:GPSLongitude", "8.0"),
            _make_element(f"{track_ns}:GPSLatitude", "47.0"),
            _make_element(f"{track_ns}:GPSMeasureMode", "2"),
        ]
        sample_iterator = [(0.0, 1.0, elements)]
        track = _aggregate_gps_track_by_sample_time(
            sample_iterator,
            lon_tag=f"{track_ns}:GPSLongitude",
            lat_tag=f"{track_ns}:GPSLatitude",
            gps_fix_tag=f"{track_ns}:GPSMeasureMode",
        )
        assert len(track) == 1
        assert track[0].fix == GPSFix.FIX_2D

    def test_gps_fix_no_fix(self):
        track_ns = "Track1"
        elements = [
            _make_element(f"{track_ns}:GPSLongitude", "8.0"),
            _make_element(f"{track_ns}:GPSLatitude", "47.0"),
            _make_element(f"{track_ns}:GPSMeasureMode", "0"),
        ]
        sample_iterator = [(0.0, 1.0, elements)]
        track = _aggregate_gps_track_by_sample_time(
            sample_iterator,
            lon_tag=f"{track_ns}:GPSLongitude",
            lat_tag=f"{track_ns}:GPSLatitude",
            gps_fix_tag=f"{track_ns}:GPSMeasureMode",
        )
        assert len(track) == 1
        assert track[0].fix == GPSFix.NO_FIX

    def test_invalid_gps_fix_is_none(self):
        track_ns = "Track1"
        elements = [
            _make_element(f"{track_ns}:GPSLongitude", "8.0"),
            _make_element(f"{track_ns}:GPSLatitude", "47.0"),
            _make_element(f"{track_ns}:GPSMeasureMode", "99"),
        ]
        sample_iterator = [(0.0, 1.0, elements)]
        track = _aggregate_gps_track_by_sample_time(
            sample_iterator,
            lon_tag=f"{track_ns}:GPSLongitude",
            lat_tag=f"{track_ns}:GPSLatitude",
            gps_fix_tag=f"{track_ns}:GPSMeasureMode",
        )
        assert len(track) == 1
        assert track[0].fix is None

    def test_gps_precision_scaled(self):
        """GPS precision should be multiplied by 100 (meters to GPSP units)."""
        track_ns = "Track1"
        elements = [
            _make_element(f"{track_ns}:GPSLongitude", "8.0"),
            _make_element(f"{track_ns}:GPSLatitude", "47.0"),
            _make_element(f"{track_ns}:GPSHPositioningError", "2.19"),
        ]
        sample_iterator = [(0.0, 1.0, elements)]
        track = _aggregate_gps_track_by_sample_time(
            sample_iterator,
            lon_tag=f"{track_ns}:GPSLongitude",
            lat_tag=f"{track_ns}:GPSLatitude",
            gps_precision_tag=f"{track_ns}:GPSHPositioningError",
        )
        assert len(track) == 1
        assert track[0].precision == pytest.approx(219.0)

    def test_multiple_points_per_sample_get_interpolated_time(self):
        """Multiple GPS points within a single sample get evenly spaced times."""
        track_ns = "Track1"
        elements = [
            _make_element(f"{track_ns}:GPSLongitude", "8.0"),
            _make_element(f"{track_ns}:GPSLatitude", "47.0"),
            _make_element(f"{track_ns}:GPSLongitude", "8.1"),
            _make_element(f"{track_ns}:GPSLatitude", "47.1"),
        ]
        sample_iterator = [(0.0, 2.0, elements)]
        track = _aggregate_gps_track_by_sample_time(
            sample_iterator,
            lon_tag=f"{track_ns}:GPSLongitude",
            lat_tag=f"{track_ns}:GPSLatitude",
        )
        assert len(track) == 2
        assert track[0].time == pytest.approx(0.0)
        assert track[1].time == pytest.approx(1.0)

    def test_empty_sample_iterator(self):
        track = _aggregate_gps_track_by_sample_time(
            iter([]),
            lon_tag="Track1:GPSLongitude",
            lat_tag="Track1:GPSLatitude",
        )
        assert track == []

    def test_sample_with_no_gps_data(self):
        """A sample with no GPS elements produces no points."""
        sample_iterator = [(0.0, 1.0, [])]
        track = _aggregate_gps_track_by_sample_time(
            sample_iterator,
            lon_tag="Track1:GPSLongitude",
            lat_tag="Track1:GPSLatitude",
        )
        assert track == []

    def test_two_samples_sorted_by_time(self):
        track_ns = "Track1"
        # Sample 2 comes before sample 1 in input
        elements1 = [
            _make_element(f"{track_ns}:GPSLongitude", "8.0"),
            _make_element(f"{track_ns}:GPSLatitude", "47.0"),
        ]
        elements2 = [
            _make_element(f"{track_ns}:GPSLongitude", "8.1"),
            _make_element(f"{track_ns}:GPSLatitude", "47.1"),
        ]
        sample_iterator = [
            (2.0, 1.0, elements2),
            (0.0, 1.0, elements1),
        ]
        track = _aggregate_gps_track_by_sample_time(
            sample_iterator,
            lon_tag=f"{track_ns}:GPSLongitude",
            lat_tag=f"{track_ns}:GPSLatitude",
        )
        assert len(track) == 2
        assert track[0].time < track[1].time


# ---------------------------------------------------------------------------
# ExifToolReadVideo.__init__
# ---------------------------------------------------------------------------


class TestExifToolReadVideoInit:
    def test_init_from_blackvue_xml(self):
        etree = _etree_from_xml(BLACKVUE_XML)
        reader = ExifToolReadVideo(etree)
        assert reader.etree is etree
        # Internal state should be populated
        assert len(reader._texts_by_tag) > 0
        assert len(reader._all_tags) > 0

    def test_init_from_gopro_xml(self):
        etree = _etree_from_xml(GOPRO_XML)
        reader = ExifToolReadVideo(etree)
        assert reader.etree is etree

    def test_init_from_insta360_xml(self):
        etree = _etree_from_xml(INSTA360_XML)
        reader = ExifToolReadVideo(etree)
        assert reader.etree is etree


# ---------------------------------------------------------------------------
# ExifToolReadVideo.extract_make / extract_model / _extract_make_and_model
# ---------------------------------------------------------------------------


class TestExtractMakeAndModel:
    def test_blackvue_make_and_model(self):
        etree = _etree_from_xml(BLACKVUE_XML)
        reader = ExifToolReadVideo(etree)
        assert reader.extract_make() == "BlackVue"
        assert reader.extract_model() == "DR900S-2CH"

    def test_gopro_make_and_model(self):
        etree = _etree_from_xml(GOPRO_XML)
        reader = ExifToolReadVideo(etree)
        assert reader.extract_make() == "GoPro"
        assert reader.extract_model() == "GoPro Max"

    def test_insta360_make_and_model(self):
        etree = _etree_from_xml(INSTA360_XML)
        reader = ExifToolReadVideo(etree)
        assert reader.extract_make() == "Insta360"
        assert reader.extract_model() == "Insta360 X3"

    def test_gopro_make_defaults_when_missing(self):
        """If GoPro:Model is present but GoPro:Make is missing, make defaults to 'GoPro'."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:GoPro='http://ns.exiftool.org/QuickTime/GoPro/1.0/'>
 <GoPro:Model>HERO11</GoPro:Model>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_make() == "GoPro"
        assert reader.extract_model() == "HERO11"

    def test_insta360_make_defaults_when_missing(self):
        """If Insta360:Model is present but Insta360:Make is missing, make defaults to 'Insta360'."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:Insta360='http://ns.exiftool.org/Trailer/Insta360/1.0/'>
 <Insta360:Model>ONE RS</Insta360:Model>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_make() == "Insta360"
        assert reader.extract_model() == "ONE RS"

    def test_no_make_no_model(self):
        """When no make/model tags exist, both return None."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_make() is None
        assert reader.extract_model() is None

    def test_make_with_whitespace_stripped(self):
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:IFD0='http://ns.exiftool.org/EXIF/IFD0/1.0/'>
 <IFD0:Make>  SomeMake  </IFD0:Make>
 <IFD0:Model>  SomeModel  </IFD0:Model>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_make() == "SomeMake"
        assert reader.extract_model() == "SomeModel"

    def test_gopro_takes_priority_over_ifd0(self):
        """GoPro namespace is checked first, so it takes priority over IFD0."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:GoPro='http://ns.exiftool.org/QuickTime/GoPro/1.0/'
 xmlns:IFD0='http://ns.exiftool.org/EXIF/IFD0/1.0/'>
 <GoPro:Make>GoPro</GoPro:Make>
 <GoPro:Model>HERO12</GoPro:Model>
 <IFD0:Make>OtherMake</IFD0:Make>
 <IFD0:Model>OtherModel</IFD0:Model>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_make() == "GoPro"
        assert reader.extract_model() == "HERO12"

    def test_userdata_make_fallback(self):
        """UserData:Make is used when IFD0:Make is not present."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:UserData='http://ns.exiftool.org/QuickTime/UserData/1.0/'>
 <UserData:Make>UserDataMake</UserData:Make>
 <UserData:Model>UserDataModel</UserData:Model>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_make() == "UserDataMake"
        assert reader.extract_model() == "UserDataModel"

    def test_make_without_model(self):
        """IFD0:Make present but no model tag anywhere returns (make, None)."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:IFD0='http://ns.exiftool.org/EXIF/IFD0/1.0/'>
 <IFD0:Make>JustMake</IFD0:Make>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_make() == "JustMake"
        assert reader.extract_model() is None


# ---------------------------------------------------------------------------
# ExifToolReadVideo.extract_camera_uuid
# ---------------------------------------------------------------------------


class TestExtractCameraUUID:
    def test_blackvue_serial(self):
        etree = _etree_from_xml(BLACKVUE_XML)
        reader = ExifToolReadVideo(etree)
        assert reader.extract_camera_uuid() == "BV900S123456"

    def test_gopro_serial(self):
        etree = _etree_from_xml(GOPRO_XML)
        reader = ExifToolReadVideo(etree)
        assert reader.extract_camera_uuid() == "C3456789012345"

    def test_insta360_serial(self):
        etree = _etree_from_xml(INSTA360_XML)
        reader = ExifToolReadVideo(etree)
        assert reader.extract_camera_uuid() == "ISN12345678"

    def test_no_serial_returns_none(self):
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_camera_uuid() is None

    def test_body_and_lens_serial_combined(self):
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:ExifIFD='http://ns.exiftool.org/EXIF/ExifIFD/1.0/'
 xmlns:UserData='http://ns.exiftool.org/QuickTime/UserData/1.0/'>
 <ExifIFD:BodySerialNumber>BODY123</ExifIFD:BodySerialNumber>
 <UserData:LensSerialNumber>LENS456</UserData:LensSerialNumber>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_camera_uuid() == "BODY123_LENS456"

    def test_serial_with_special_chars_sanitized(self):
        """Serial numbers with non-alphanumeric characters are sanitized."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:IFD0='http://ns.exiftool.org/EXIF/IFD0/1.0/'>
 <IFD0:SerialNumber>SN-123_456</IFD0:SerialNumber>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        # sanitize_serial removes non-alphanumeric chars
        assert reader.extract_camera_uuid() == "SN123456"

    def test_empty_serial_after_sanitization_returns_none(self):
        """A serial that becomes empty after sanitization yields None."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:IFD0='http://ns.exiftool.org/EXIF/IFD0/1.0/'>
 <IFD0:SerialNumber>---</IFD0:SerialNumber>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_camera_uuid() is None

    def test_gopro_serial_priority_over_generic(self):
        """GoPro:SerialNumber is checked before generic ExifIFD:SerialNumber."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:GoPro='http://ns.exiftool.org/QuickTime/GoPro/1.0/'
 xmlns:ExifIFD='http://ns.exiftool.org/EXIF/ExifIFD/1.0/'>
 <GoPro:SerialNumber>GPSERIAL</GoPro:SerialNumber>
 <ExifIFD:SerialNumber>EXIFSERIAL</ExifIFD:SerialNumber>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_camera_uuid() == "GPSERIAL"

    def test_dji_serial(self):
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:DJI='http://ns.exiftool.org/MakerNotes/DJI/1.0/'>
 <DJI:SerialNumber>DJI123456</DJI:SerialNumber>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_camera_uuid() == "DJI123456"

    def test_lens_serial_only(self):
        """Only lens serial, no body serial."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:ExifIFD='http://ns.exiftool.org/EXIF/ExifIFD/1.0/'>
 <ExifIFD:LensSerialNumber>LENS789</ExifIFD:LensSerialNumber>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_camera_uuid() == "LENS789"


# ---------------------------------------------------------------------------
# ExifToolReadVideo.extract_gps_track (integration)
# ---------------------------------------------------------------------------


class TestExtractGpsTrack:
    def test_blackvue_quicktime_gps(self):
        """BlackVue uses QuickTime namespace - the first path in extract_gps_track."""
        etree = _etree_from_xml(BLACKVUE_XML)
        reader = ExifToolReadVideo(etree)
        track = reader.extract_gps_track()
        assert len(track) == 3
        # Time should be normalized (starts at 0)
        assert track[0].time == pytest.approx(0.0)
        assert track[1].time == pytest.approx(1.0)
        assert track[2].time == pytest.approx(2.0)
        # Check coordinates of first point
        assert track[0].lat == pytest.approx(37.265547)
        assert track[0].lon == pytest.approx(28.213497)
        assert track[0].alt == pytest.approx(402.9)
        assert track[0].angle == pytest.approx(133.46)

    def test_insta360_gps(self):
        """Insta360 uses Insta360 namespace - the second path in extract_gps_track."""
        etree = _etree_from_xml(INSTA360_XML)
        reader = ExifToolReadVideo(etree)
        track = reader.extract_gps_track()
        assert len(track) == 2
        assert track[0].lat == pytest.approx(47.371)
        assert track[0].lon == pytest.approx(8.542)
        assert track[0].alt == pytest.approx(408.5)

    def test_gopro_track_gps(self):
        """GoPro uses Track namespace - the third path in extract_gps_track."""
        etree = _etree_from_xml(GOPRO_XML)
        reader = ExifToolReadVideo(etree)
        track = reader.extract_gps_track()
        assert len(track) == 2
        assert track[0].lat == pytest.approx(47.359832)
        assert track[0].lon == pytest.approx(8.522706)

    def test_empty_gps_track(self):
        """When no GPS data is present, returns empty list."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:IFD0='http://ns.exiftool.org/EXIF/IFD0/1.0/'>
 <IFD0:Make>Unknown</IFD0:Make>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        track = reader.extract_gps_track()
        assert track == []

    def test_quicktime_preferred_over_track(self):
        """If both QuickTime and Track GPS data exist, QuickTime is used."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:QuickTime='http://ns.exiftool.org/QuickTime/QuickTime/1.0/'
 xmlns:Track1='http://ns.exiftool.org/QuickTime/Track1/1.0/'>
 <QuickTime:GPSDateTime>2019:09:02 10:23:28.00Z</QuickTime:GPSDateTime>
 <QuickTime:GPSLatitude>37.0</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>28.0</QuickTime:GPSLongitude>
 <Track1:SampleTime>0</Track1:SampleTime>
 <Track1:SampleDuration>1.0</Track1:SampleDuration>
 <Track1:GPSLatitude>47.0</Track1:GPSLatitude>
 <Track1:GPSLongitude>8.0</Track1:GPSLongitude>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        track = reader.extract_gps_track()
        # QuickTime is preferred, so lat should be ~37, not ~47
        assert len(track) >= 1
        assert track[0].lat == pytest.approx(37.0)


# ---------------------------------------------------------------------------
# ExifToolReadVideo._extract_gps_track_from_quicktime
# ---------------------------------------------------------------------------


class TestExtractGpsTrackFromQuicktime:
    def test_missing_required_tags_returns_empty(self):
        """Without all three required tags, returns empty list."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:QuickTime='http://ns.exiftool.org/QuickTime/QuickTime/1.0/'>
 <QuickTime:GPSLatitude>37.0</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>28.0</QuickTime:GPSLongitude>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        # GPSDateTime is missing, so _extract_gps_track_from_quicktime returns []
        track = reader._extract_gps_track_from_quicktime()
        assert track == []

    def test_custom_namespace_insta360(self):
        etree = _etree_from_xml(INSTA360_XML)
        reader = ExifToolReadVideo(etree)
        track = reader._extract_gps_track_from_quicktime(namespace="Insta360")
        assert len(track) == 2
        assert track[0].lat == pytest.approx(47.371)

    def test_custom_namespace_not_present(self):
        """Using a namespace that has no data returns empty."""
        etree = _etree_from_xml(BLACKVUE_XML)
        reader = ExifToolReadVideo(etree)
        track = reader._extract_gps_track_from_quicktime(namespace="Insta360")
        assert track == []


# ---------------------------------------------------------------------------
# ExifToolReadVideo._extract_gps_track_from_track
# ---------------------------------------------------------------------------


class TestExtractGpsTrackFromTrack:
    def test_gopro_track_data(self):
        etree = _etree_from_xml(GOPRO_XML)
        reader = ExifToolReadVideo(etree)
        track = reader._extract_gps_track_from_track()
        assert len(track) == 2
        assert track[0].lat == pytest.approx(47.359832)
        assert track[0].lon == pytest.approx(8.522706)
        assert track[0].alt == pytest.approx(414.9)
        # GPSMeasureMode=3 -> FIX_3D
        assert track[0].fix == GPSFix.FIX_3D
        # GPSHPositioningError=2.19 -> 219.0 after *100
        assert track[0].precision == pytest.approx(219.0)

    def test_no_track_data_returns_empty(self):
        etree = _etree_from_xml(BLACKVUE_XML)
        reader = ExifToolReadVideo(etree)
        # BlackVue doesn't have Track namespace data
        track = reader._extract_gps_track_from_track()
        assert track == []

    def test_track2_namespace(self):
        """GPS data in Track2 (not Track1) is still found."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:Track2='http://ns.exiftool.org/QuickTime/Track2/1.0/'>
 <Track2:SampleTime>0</Track2:SampleTime>
 <Track2:SampleDuration>1.0</Track2:SampleDuration>
 <Track2:GPSLatitude>47.0</Track2:GPSLatitude>
 <Track2:GPSLongitude>8.0</Track2:GPSLongitude>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        track = reader._extract_gps_track_from_track()
        assert len(track) == 1
        assert track[0].lat == pytest.approx(47.0)

    def test_track_with_incomplete_tags_skipped(self):
        """Track namespace missing SampleTime/SampleDuration is skipped."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:Track1='http://ns.exiftool.org/QuickTime/Track1/1.0/'>
 <Track1:GPSLatitude>47.0</Track1:GPSLatitude>
 <Track1:GPSLongitude>8.0</Track1:GPSLongitude>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        track = reader._extract_gps_track_from_track()
        assert track == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_gps_point(self):
        """Single GPS point still works."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:QuickTime='http://ns.exiftool.org/QuickTime/QuickTime/1.0/'>
 <QuickTime:GPSDateTime>2019:09:02 10:23:28.00Z</QuickTime:GPSDateTime>
 <QuickTime:GPSLatitude>37.0</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>28.0</QuickTime:GPSLongitude>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        track = reader.extract_gps_track()
        assert len(track) == 1
        assert track[0].time == pytest.approx(0.0)

    def test_duplicate_points_removed(self):
        """Consecutive identical GPS points are deduplicated."""
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:QuickTime='http://ns.exiftool.org/QuickTime/QuickTime/1.0/'>
 <QuickTime:GPSDateTime>2019:09:02 10:23:28.00Z</QuickTime:GPSDateTime>
 <QuickTime:GPSLatitude>37.0</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>28.0</QuickTime:GPSLongitude>
 <QuickTime:GPSDateTime>2019:09:02 10:23:28.00Z</QuickTime:GPSDateTime>
 <QuickTime:GPSLatitude>37.0</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>28.0</QuickTime:GPSLongitude>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        track = reader.extract_gps_track()
        assert len(track) == 1

    def test_rdf_description_with_no_children(self):
        xml = """\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'>
</rdf:Description>
</rdf:RDF>
"""
        reader = ExifToolReadVideo(_etree_from_xml(xml))
        assert reader.extract_gps_track() == []
        assert reader.extract_make() is None
        assert reader.extract_model() is None
        assert reader.extract_camera_uuid() is None
