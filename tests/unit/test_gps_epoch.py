# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Regression tests for the epoch of CAMM GPS timestamps.

The CAMM box field is called ``time_gps_epoch``, but producers disagree about
what goes in it: Labpano cameras write GPS time (seconds since 1980-01-06),
while Insta360 and mapillary_tools itself write Unix time. Confusing the two
is a ~315,964,800s (10 year) error.

The invariant these tests protect: ``CAMMGPSPoint.epoch_time`` is *always*
Unix time in memory. It is converted from GPS time once, when the CAMM track is
parsed, and never on the way out: mapillary_tools writes Unix time whatever the
make.

Which epoch a track records is decided by the mvhd creation time of the video
when that is conclusive, and by the make otherwise. The CAMM tracks
mapillary_tools writes carry the make and the creation time of their source,
so for a Labpano video it is the creation time that says Unix time.
"""

from __future__ import annotations

import io
import typing as T
from pathlib import Path

import pytest
from mapillary_tools import geo, telemetry, types, uploader
from mapillary_tools.camm import camm_builder, camm_parser
from mapillary_tools.geotag.options import SourceOption, SourceType
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor
from mapillary_tools.geotag.video_extractors.native import CAMMVideoExtractor
from mapillary_tools.mp4 import construct_mp4_parser as cparser, simple_mp4_builder


# Seconds between the two epochs, i.e. the size of the bug
GPS_UNIX_DELTA = 315964800

# 2026-08-12T08:26:27Z, taken from a PanoX V2 capture
A_GPS_TIME = 1470558405.9798455
A_UNIX_TIME = 1786523187.9798455

# Seconds between the mp4 epoch (1904-01-01) and the Unix epoch
MP4_UNIX_DELTA = 2082844800

# Labpano stamps the creation time at the end of the recording
A_CREATION_TIME = A_UNIX_TIME + 600


def _camm_point(time: float, epoch_time: float) -> telemetry.CAMMGPSPoint:
    return telemetry.CAMMGPSPoint(
        time=time,
        lat=37.8436443,
        lon=14.9886571,
        alt=1202.345,
        angle=None,
        epoch_time=epoch_time,
        gps_fix_type=3,
        horizontal_accuracy=0.0,
        vertical_accuracy=0.0,
        velocity_east=0.0,
        velocity_north=0.0,
        velocity_up=0.0,
        speed_accuracy=0.0,
    )


def _gps_point(time: float, epoch_time: float | None) -> telemetry.GPSPoint:
    return telemetry.GPSPoint(
        time=time,
        lat=37.8436443,
        lon=14.9886571,
        alt=1202.345,
        angle=None,
        epoch_time=epoch_time,
        fix=telemetry.GPSFix.FIX_3D,
        precision=None,
        ground_speed=None,
    )


def _write_camm_mp4(
    points: T.Sequence[geo.Point], make: str, creation_time: float | None
) -> bytes:
    """
    Write points as a CAMM track into an empty mp4, the way the uploader does.

    creation_time is the Unix time to put in mvhd, or None to leave it unset.
    """
    mp4_creation_time = (
        0 if creation_time is None else int(creation_time) + MP4_UNIX_DELTA
    )
    mvhd: cparser.BoxDict = {
        "type": b"mvhd",
        "data": {
            "creation_time": mp4_creation_time,
            "modification_time": mp4_creation_time,
            "timescale": 1000,
            "duration": 10000,
        },
    }
    src = cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist(
        [
            {"type": b"ftyp", "data": b"test"},
            {"type": b"moov", "data": [mvhd]},
        ]
    )
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=list(points),
        make=make,
        model="PanoX V2",
    )
    camm_info = uploader.VideoUploader.prepare_camm_info(metadata)
    target_fp = simple_mp4_builder.transform_mp4(
        io.BytesIO(src), camm_builder.camm_sample_generator2(camm_info)
    )
    return target_fp.read()


def _read_camm(data: bytes) -> camm_parser.CAMMInfo:
    camm_info = camm_parser.extract_camm_info(io.BytesIO(data))
    assert camm_info is not None
    return camm_info


def _unix_times(camm_info: camm_parser.CAMMInfo) -> list[float]:
    return [p.epoch_time for p in camm_info.gps or []]


# A two point track at A_UNIX_TIME, as parse_gpx() or the parser would return it
UNIX_TIMES = [A_UNIX_TIME, A_UNIX_TIME + 1]


def _unix_track() -> list[telemetry.CAMMGPSPoint]:
    return [
        _camm_point(time=float(idx), epoch_time=epoch_time)
        for idx, epoch_time in enumerate(UNIX_TIMES)
    ]


class TestEpochConversion:
    def test_known_instant(self):
        assert telemetry.gps_epoch_to_unix(A_GPS_TIME) == A_UNIX_TIME

    def test_leap_seconds_accumulate(self):
        # No leap seconds had accumulated at the GPS epoch itself
        assert telemetry.gps_epoch_to_unix(0) == GPS_UNIX_DELTA
        # 18 by 2026, so the naive +315964800 conversion lands 18s too late
        assert (
            telemetry.gps_epoch_to_unix(A_GPS_TIME) == A_GPS_TIME + GPS_UNIX_DELTA - 18
        )


class TestParseBoundaryNormalization:
    """The one place an epoch conversion is allowed to happen."""

    def test_gps_epoch_producer_is_converted(self):
        points = [_camm_point(time=0.0, epoch_time=A_GPS_TIME)]
        camm_parser._normalize_gps_epochs(points, "Labpano")
        assert points[0].epoch_time == A_UNIX_TIME
        assert points[0].get_unix_time() == A_UNIX_TIME

    @pytest.mark.parametrize("make", ["Insta360", "GoPro", "", "Unknown"])
    def test_unix_producers_are_left_alone(self, make: str):
        """Converting these would push them ~10 years into the future."""
        points = [_camm_point(time=0.0, epoch_time=A_UNIX_TIME)]
        camm_parser._normalize_gps_epochs(points, make)
        assert points[0].epoch_time == A_UNIX_TIME

    def test_make_match_is_case_insensitive(self):
        for make in ["labpano", "LABPANO", " Labpano "]:
            points = [_camm_point(time=0.0, epoch_time=A_GPS_TIME)]
            camm_parser._normalize_gps_epochs(points, make)
            assert points[0].epoch_time == A_UNIX_TIME, make

    def test_invalid_timestamps_are_not_converted(self):
        """A zero timestamp must stay zero, not become 1980."""
        points = [_camm_point(time=0.0, epoch_time=0.0)]
        camm_parser._normalize_gps_epochs(points, "Labpano")
        assert points[0].epoch_time == 0.0
        assert points[0].get_unix_time() is None

    @pytest.mark.parametrize(
        "make", ["Labpano Technology Co.,Ltd", "LABPANO TECHNOLOGY", "Labpano Pilot"]
    )
    def test_make_variants_are_matched(self, make: str):
        """Firmware reports the vendor in more than one form."""
        points = [_camm_point(time=0.0, epoch_time=A_GPS_TIME)]
        camm_parser._normalize_gps_epochs(points, make)
        assert points[0].epoch_time == A_UNIX_TIME


class TestCreationTimeEvidence:
    """The creation time decides the epoch whenever it is conclusive."""

    @pytest.mark.parametrize("make", ["", "Insta360", "Some Future Camera"])
    def test_gps_time_is_recognized_whatever_the_make(self, make: str):
        assert camm_parser._records_gps_time(A_GPS_TIME, make, A_CREATION_TIME)

    @pytest.mark.parametrize("make", ["Labpano", "Labpano Technology Co.,Ltd"])
    def test_unix_time_is_recognized_whatever_the_make(self, make: str):
        assert not camm_parser._records_gps_time(A_UNIX_TIME, make, A_CREATION_TIME)

    def test_inconclusive_creation_time_falls_back_to_make(self):
        # A GoPro HERO7 recorded in 2022 reports 2016
        meaningless = A_UNIX_TIME - 6 * 365 * 24 * 3600
        assert camm_parser._records_gps_time(A_GPS_TIME, "Labpano", meaningless)
        assert not camm_parser._records_gps_time(A_UNIX_TIME, "Insta360", meaningless)

    def test_missing_creation_time_falls_back_to_make(self):
        assert camm_parser._records_gps_time(A_GPS_TIME, "Labpano", None)
        assert not camm_parser._records_gps_time(A_UNIX_TIME, "Insta360", None)

    def test_unknown_make_in_gps_time_is_read_from_the_file(self):
        """The mvhd creation time reaches the decision through the parser."""
        data = _write_camm_mp4(
            [_camm_point(time=0.0, epoch_time=A_GPS_TIME)],
            make="",
            creation_time=A_CREATION_TIME,
        )
        assert _unix_times(_read_camm(data)) == [A_UNIX_TIME]

    def test_labpano_original_without_creation_time_is_converted(self):
        data = _write_camm_mp4(
            [_camm_point(time=0.0, epoch_time=A_GPS_TIME)], "Labpano", None
        )
        assert _unix_times(_read_camm(data)) == [A_UNIX_TIME]


class TestMedianDecides:
    """The whole track decides its epoch, not its first timestamp."""

    def _read_back(self, raw_times: list[float]) -> list[float]:
        points = [
            _camm_point(time=float(idx), epoch_time=raw_time)
            for idx, raw_time in enumerate(raw_times)
        ]
        # Written as is, so the raw times are what the reader sees
        data = _write_camm_mp4(points, "Labpano", A_CREATION_TIME)
        return _unix_times(_read_camm(data))

    def test_stray_unix_time_does_not_flip_a_gps_time_track(self):
        raw_times = [A_UNIX_TIME] + [A_GPS_TIME + t for t in range(1, 10)]
        assert self._read_back(raw_times)[1:] == [A_UNIX_TIME + t for t in range(1, 10)]

    def test_stray_gps_time_does_not_flip_a_unix_time_track(self):
        raw_times = [A_GPS_TIME] + [A_UNIX_TIME + t for t in range(1, 10)]
        assert self._read_back(raw_times)[1:] == [A_UNIX_TIME + t for t in range(1, 10)]


class TestWriteRoundTrip:
    """
    Whatever mapillary_tools writes must read back to the same Unix times.

    It writes Unix time whatever the make. The source make is copied into the
    output, so for a Labpano video it is the creation time, copied from the
    source too, that keeps the reader from converting it one GPS epoch later:
    2026 used to become 2036.
    """

    @pytest.mark.parametrize(
        "make", ["Labpano", "Labpano Technology Co.,Ltd", "Insta360", ""]
    )
    def test_round_trip(self, make: str):
        data = _write_camm_mp4(_unix_track(), make, A_CREATION_TIME)
        assert _unix_times(_read_camm(data)) == UNIX_TIMES

    def test_reprocessing_output_is_stable(self):
        """process_and_upload output, processed again, is the same track."""
        data = _write_camm_mp4(_unix_track(), "Labpano", A_CREATION_TIME)
        for _ in range(2):
            camm_info = _read_camm(data)
            assert _unix_times(camm_info) == UNIX_TIMES
            data = _write_camm_mp4(camm_info.gps or [], camm_info.make, A_CREATION_TIME)

    @pytest.mark.parametrize("make", ["Labpano", "Insta360", ""])
    def test_written_as_unix_time_whatever_the_make(self, monkeypatch, make: str):
        data = _write_camm_mp4(_unix_track(), make, A_CREATION_TIME)
        monkeypatch.setattr(camm_parser, "_normalize_gps_epochs", lambda *_: None)
        assert _unix_times(_read_camm(data)) == UNIX_TIMES


class TestMixedCAMMTypes:
    """A track may mix type 6 and type 5 samples; neither may be dropped."""

    def _mixed_track(self) -> list[geo.Point]:
        return [
            geo.Point(time=0.0, lat=37.0, lon=14.0, alt=None, angle=None),
            _camm_point(time=1.0, epoch_time=A_UNIX_TIME + 1),
            geo.Point(time=2.0, lat=37.0, lon=14.0, alt=None, angle=None),
            _camm_point(time=3.0, epoch_time=A_UNIX_TIME + 3),
        ]

    def test_extractor_returns_both_types_in_order(self, tmp_path: Path):
        video_path = tmp_path / "mixed.mp4"
        video_path.write_bytes(
            _write_camm_mp4(self._mixed_track(), "Labpano", A_CREATION_TIME)
        )

        points = CAMMVideoExtractor(video_path).extract().points

        assert [p.time for p in points] == [0.0, 1.0, 2.0, 3.0]
        assert [type(p) for p in points] == [
            geo.Point,
            telemetry.CAMMGPSPoint,
            geo.Point,
            telemetry.CAMMGPSPoint,
        ]

    def test_gpx_clock_anchors_on_the_first_timestamped_point(self):
        clock = GPXVideoExtractor._read_video_clock(self._mixed_track())
        # Anchored at the type 6 point 1s into the video, which is at
        # A_UNIX_TIME + 1, not at the type 5 point the track starts with
        assert clock is not None
        # So a GPX point recorded 30s before the video starts lands at -30s
        assert clock.to_video_time(A_UNIX_TIME - 30) == -30.0


class TestPointAccessors:
    def test_both_point_types_report_unix_time(self):
        assert _camm_point(0.0, A_UNIX_TIME).get_unix_time() == A_UNIX_TIME
        assert _gps_point(0.0, A_UNIX_TIME).get_unix_time() == A_UNIX_TIME

    def test_invalid_timestamps_are_ignored(self):
        assert _camm_point(time=0.0, epoch_time=0.0).get_unix_time() is None
        assert _gps_point(time=0.0, epoch_time=None).get_unix_time() is None
        assert _gps_point(time=0.0, epoch_time=0.0).get_unix_time() is None
        # A plain Point carries no absolute timestamp at all
        assert (
            geo.Point(time=1.0, lat=0, lon=0, alt=None, angle=None).get_unix_time()
            is None
        )


class TestGPXSync:
    """A GPX recorded alongside the video must sync to ~0, not to ~10 years."""

    def test_camm_video_syncs_to_zero(self):
        video_points = [_camm_point(time=0.0, epoch_time=A_UNIX_TIME)]
        clock = GPXVideoExtractor._read_video_clock(video_points)
        assert clock is not None
        assert clock.to_video_time(A_UNIX_TIME) == 0.0

    def test_gopro_video_syncs_to_zero(self):
        video_points = [_gps_point(time=0.0, epoch_time=A_UNIX_TIME)]
        clock = GPXVideoExtractor._read_video_clock(video_points)
        assert clock is not None
        assert clock.to_video_time(A_UNIX_TIME) == 0.0

    def test_real_offset_is_preserved(self):
        video_points = [_camm_point(time=0.0, epoch_time=A_UNIX_TIME)]
        clock = GPXVideoExtractor._read_video_clock(video_points)
        assert clock is not None
        assert clock.to_video_time(A_UNIX_TIME + 30) == 30.0

    def test_missing_video_timestamp_yields_no_clock(self):
        video_points = [_camm_point(time=0.0, epoch_time=0.0)]
        assert GPXVideoExtractor._read_video_clock(video_points) is None

    @pytest.mark.parametrize("video_point", [_camm_point, _gps_point])
    def test_video_gps_starting_late_syncs_to_video_time(self, video_point):
        """
        The clock is anchored at the video time of the first video GPS point,
        not at video time 0, or the GPX track would land early by that time.
        """
        # The video's GPS starts 5s into the video
        video_points = [
            video_point(time=5.0 + t, epoch_time=A_UNIX_TIME + 5 + t) for t in range(10)
        ]

        clock = GPXVideoExtractor._read_video_clock(video_points)

        # Recorded at the same instant as the first video GPS point, so it
        # lands at the same video time
        assert clock is not None
        assert clock.to_video_time(A_UNIX_TIME + 5) == 5.0


class TestEditListOverflow:
    """An oversized initial gap must not abort the upload."""

    def test_small_offset_stays_version_0(self):
        points = [geo.Point(time=1.5, lat=0, lon=0, alt=None, angle=None)]
        elst = camm_builder._create_edit_list_from_points([points], 1000, 1000)
        assert elst["data"]["version"] == 0
        assert elst["data"]["entries"][0]["segment_duration"] == 1500

    def test_oversized_offset_falls_back_to_version_1(self):
        # The exact shape of the reported crash: a whole GPS epoch of offset
        points = [geo.Point(time=GPS_UNIX_DELTA, lat=0, lon=0, alt=None, angle=None)]
        elst = camm_builder._create_edit_list_from_points([points], 1000, 1000)
        assert elst["data"]["version"] == 1
        assert elst["data"]["entries"][0]["segment_duration"] == GPS_UNIX_DELTA * 1000
        # Must serialize rather than raise construct.core.FormatFieldError
        assert cparser.EditBox.build(elst["data"])


class TestSourceOption:
    def test_explicit_source_path_is_not_dropped(self):
        opt = SourceOption.from_dict(
            {
                "source": "gpx",
                "pattern": "%g.gpx",
                "source_path": "/tmp/explicit.gpx",
            }
        )
        assert opt.source is SourceType.GPX
        assert opt.source_path is not None
        assert opt.source_path.source_path == Path("/tmp/explicit.gpx")
        # source_path wins over pattern when resolving
        assert opt.source_path.resolve(Path("/data/video.mp4")) == Path(
            "/tmp/explicit.gpx"
        )
