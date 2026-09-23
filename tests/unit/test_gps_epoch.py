# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests for the epoch of CAMM GPS timestamps.

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

import datetime
import io
import logging
import pickle
import shutil
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from mapillary_tools import exceptions, exiftool_read, geo, telemetry, types, uploader
from mapillary_tools.camm import camm_builder, camm_parser
from mapillary_tools.exiftool_read_video import ExifToolReadVideo
from mapillary_tools.exiftool_runner import ExiftoolRunner
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import SourceOption, SourcePathOption, SourceType
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
            "duration": 36000 * 1000,
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

    # Labpano stamps the creation time at the end of the recording
    CREATION_TIME = A_UNIX_TIME + 600

    @pytest.mark.parametrize("make", ["", "Insta360", "Some Future Camera"])
    def test_gps_time_is_recognized_whatever_the_make(self, make: str):
        assert camm_parser._records_gps_time(A_GPS_TIME, make, self.CREATION_TIME)

    @pytest.mark.parametrize("make", ["Labpano", "Labpano Technology Co.,Ltd"])
    def test_unix_time_is_recognized_whatever_the_make(self, make: str):
        assert not camm_parser._records_gps_time(A_UNIX_TIME, make, self.CREATION_TIME)

    def test_inconclusive_creation_time_falls_back_to_make(self):
        # A GoPro HERO7 recorded in 2022 reports 2016
        meaningless = A_UNIX_TIME - 6 * 365 * 24 * 3600
        assert camm_parser._records_gps_time(A_GPS_TIME, "Labpano", meaningless)
        assert not camm_parser._records_gps_time(A_UNIX_TIME, "Insta360", meaningless)

    def test_unknown_make_in_gps_time_is_read_from_the_file(self):
        """The mvhd creation time reaches the decision through the parser."""
        data = _write_camm_mp4(
            [_camm_point(time=0.0, epoch_time=A_GPS_TIME)],
            make="",
            creation_time=self.CREATION_TIME,
        )
        assert _unix_times(_read_camm(data)) == [A_UNIX_TIME]


class TestOneSampleDoesNotDecide:
    """The whole track decides its epoch, not its first timestamp."""

    CREATION_TIME = A_UNIX_TIME + 600

    def _read_back(self, raw_times: list[float]) -> list[float]:
        points = [
            _camm_point(time=float(idx), epoch_time=raw_time)
            for idx, raw_time in enumerate(raw_times)
        ]
        # Written as is, so the raw times are what the reader sees
        data = _write_camm_mp4(points, "Labpano", self.CREATION_TIME)
        return _unix_times(_read_camm(data))

    def test_stray_unix_time_does_not_flip_a_gps_time_track(self):
        raw_times = [A_UNIX_TIME] + [A_GPS_TIME + t for t in range(1, 10)]
        unix_times = self._read_back(raw_times)
        assert unix_times[1:] == [A_UNIX_TIME + t for t in range(1, 10)]

    def test_stray_gps_time_does_not_flip_a_unix_time_track(self):
        raw_times = [A_GPS_TIME] + [A_UNIX_TIME + t for t in range(1, 10)]
        unix_times = self._read_back(raw_times)
        assert unix_times[1:] == [A_UNIX_TIME + t for t in range(1, 10)]


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
        data = _write_camm_mp4(_unix_track(), make, A_UNIX_TIME + 600)
        assert _unix_times(_read_camm(data)) == UNIX_TIMES

    @pytest.mark.parametrize("make", ["Insta360", ""])
    def test_round_trip_without_creation_time(self, make: str):
        data = _write_camm_mp4(_unix_track(), make, None)
        assert _unix_times(_read_camm(data)) == UNIX_TIMES

    def test_reprocessing_output_is_stable(self):
        """process_and_upload output, processed again, is the same track."""
        data = _write_camm_mp4(_unix_track(), "Labpano", A_UNIX_TIME + 600)
        for _ in range(2):
            camm_info = _read_camm(data)
            assert _unix_times(camm_info) == UNIX_TIMES
            data = _write_camm_mp4(
                camm_info.gps or [], camm_info.make, A_UNIX_TIME + 600
            )

    @pytest.mark.parametrize("make", ["Labpano", "Insta360", ""])
    def test_written_as_unix_time_whatever_the_make(self, monkeypatch, make: str):
        data = _write_camm_mp4(_unix_track(), make, A_UNIX_TIME + 600)
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
            _write_camm_mp4(self._mixed_track(), "Labpano", A_UNIX_TIME + 600)
        )

        points = CAMMVideoExtractor(video_path).extract().points

        assert [p.time for p in points] == [0.0, 1.0, 2.0, 3.0]
        assert [type(p) for p in points] == [
            geo.Point,
            telemetry.CAMMGPSPoint,
            geo.Point,
            telemetry.CAMMGPSPoint,
        ]

    def test_gpx_offset_anchors_on_the_first_timestamped_point(self):
        # The GPX starts 30s before the video does
        gpx_points = [_camm_point(time=A_UNIX_TIME - 30, epoch_time=A_UNIX_TIME - 30)]
        assert GPXVideoExtractor._gpx_offset(gpx_points, self._mixed_track()) == -30.0


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


class TestGPXOffset:
    """A GPX recorded alongside the video must sync to ~0, not to ~10 years."""

    def test_camm_video_syncs_to_zero(self):
        gpx_points = [_camm_point(time=A_UNIX_TIME, epoch_time=A_UNIX_TIME)]
        video_points = [_camm_point(time=0.0, epoch_time=A_UNIX_TIME)]
        assert GPXVideoExtractor._gpx_offset(gpx_points, video_points) == 0.0

    def test_gopro_video_syncs_to_zero(self):
        gpx_points = [_camm_point(time=A_UNIX_TIME, epoch_time=A_UNIX_TIME)]
        video_points = [_gps_point(time=0.0, epoch_time=A_UNIX_TIME)]
        assert GPXVideoExtractor._gpx_offset(gpx_points, video_points) == 0.0

    def test_real_offset_is_preserved(self):
        gpx_points = [_camm_point(time=A_UNIX_TIME + 30, epoch_time=A_UNIX_TIME + 30)]
        video_points = [_camm_point(time=0.0, epoch_time=A_UNIX_TIME)]
        assert GPXVideoExtractor._gpx_offset(gpx_points, video_points) == 30.0

    def test_missing_video_timestamp_yields_no_offset(self):
        gpx_points = [_camm_point(time=A_UNIX_TIME, epoch_time=A_UNIX_TIME)]
        video_points = [_camm_point(time=0.0, epoch_time=0.0)]
        assert GPXVideoExtractor._gpx_offset(gpx_points, video_points) == 0.0

    def test_video_gps_starting_late_syncs_to_video_time(self):
        """
        The offset is to video time 0, not to the first video GPS point, or
        the GPX track would land early by that point's time.
        """
        gpx_points = _gpx_track(A_UNIX_TIME, 20)
        # The video's GPS starts 5s into the video
        video_points = [
            _camm_point(time=5.0 + t, epoch_time=A_UNIX_TIME + 5 + t) for t in range(10)
        ]

        offset = GPXVideoExtractor._gpx_offset(gpx_points, video_points)
        GPXVideoExtractor._rebase_times(gpx_points, offset=offset)

        # Recorded at the same instant as the first video GPS point, so it
        # lands at the same video time
        assert gpx_points[5].time == 5.0


def _gpx_track(start: float, duration: int) -> list[telemetry.CAMMGPSPoint]:
    return [
        _camm_point(time=start + t, epoch_time=start + t) for t in range(duration + 1)
    ]


def _write_gpx(path: Path, points: T.Sequence[geo.Point]) -> None:
    trkpts = "".join(
        f'<trkpt lat="{p.lat}" lon="{p.lon}"><time>{_isoformat(p.time)}</time></trkpt>'
        for p in points
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{trkpts}</trkseg></trk></gpx>"
    )


def _isoformat(unix_time: float) -> str:
    return datetime.datetime.fromtimestamp(unix_time, datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class TestGPXTimeGap:
    """
    A GPX track that misses the video by more than a day must fail, not sync.

    The edit list no longer overflows on a huge offset, so this is what keeps
    an epoch mix-up or a GPX file from another day from being uploaded. A
    smaller gap only warns, since it can be legitimate.
    """

    # A 10s video track starting at A_UNIX_TIME
    VIDEO = [_camm_point(time=float(t), epoch_time=A_UNIX_TIME + t) for t in range(11)]

    def _check(
        self,
        gpx_points: list[telemetry.CAMMGPSPoint],
        video: T.Sequence[geo.Point] = VIDEO,
    ) -> None:
        extractor = GPXVideoExtractor(Path("video.mp4"), Path("track.gpx"))
        offset = extractor._gpx_offset(gpx_points, video)
        extractor._check_time_gap(gpx_points, video, offset)

    @pytest.mark.parametrize(
        "start, duration",
        [
            # Starts 30s before the video and ends during it
            (A_UNIX_TIME - 30, 35),
            # Starts during the video
            (A_UNIX_TIME + 5, 60),
            # A long recording that spans the video
            (A_UNIX_TIME - 3 * 24 * 3600, 6 * 24 * 3600),
        ],
    )
    def test_overlapping_gpx_passes_silently(self, caplog, start: float, duration: int):
        with caplog.at_level(logging.WARNING):
            self._check(_gpx_track(start, duration))
        assert not caplog.records

    @pytest.mark.parametrize(
        "start",
        [
            # Ended a minute before the video started
            A_UNIX_TIME - 70,
            # Naive GPX timestamps read in a time zone 9h off
            A_UNIX_TIME + 9 * 3600,
            # Starts after the video's own GPS gives out
            A_UNIX_TIME + 60,
        ],
    )
    def test_small_gap_warns(self, caplog, start: float):
        with caplog.at_level(logging.WARNING):
            self._check(_gpx_track(start, 10))
        [record] = caplog.records
        assert "video.mp4" in record.getMessage()
        assert "track.gpx" in record.getMessage()

    @pytest.mark.parametrize(
        "start",
        [A_UNIX_TIME + 2 * 24 * 3600, A_UNIX_TIME - 3 * 24 * 3600],
    )
    def test_gap_of_days_raises(self, start: float):
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._check(_gpx_track(start, 10))
        assert "video.mp4" in str(info.value)
        assert "track.gpx" in str(info.value)

    def test_epoch_mixup_raises(self):
        """Video timestamps left in GPS time sync ten years off."""
        video = [
            _camm_point(time=float(t), epoch_time=A_GPS_TIME + t) for t in range(11)
        ]
        gpx_points = _gpx_track(A_UNIX_TIME, 10)
        offset = GPXVideoExtractor._gpx_offset(gpx_points, video)
        assert abs(offset - (GPS_UNIX_DELTA - 18)) < 1
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError):
            self._check(gpx_points, video)

    def test_error_survives_a_worker_process(self):
        """Videos are geotagged in a process pool, so the error gets pickled."""
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._check(_gpx_track(A_UNIX_TIME + 2 * 24 * 3600, 10))

        unpickled = pickle.loads(pickle.dumps(info.value))

        assert str(unpickled) == str(info.value)
        assert vars(unpickled) == vars(info.value)

    def test_extract_syncs_labpano_video_to_its_gpx(self, tmp_path: Path):
        video_path = tmp_path / "labpano.mp4"
        video_path.write_bytes(
            _write_camm_mp4(self.VIDEO, "Labpano", A_UNIX_TIME + 600)
        )
        gpx_path = tmp_path / "labpano.gpx"
        _write_gpx(gpx_path, _gpx_track(int(A_UNIX_TIME) - 5, 20))

        points = GPXVideoExtractor(video_path, gpx_path).extract().points

        # The GPX starts ~5s before the video, whose GPS starts at video time 0
        assert -6 < points[0].time < -4

    def _write_video_and_gpx(
        self, tmp_path: Path, gpx_start: float
    ) -> tuple[Path, Path]:
        video_path = tmp_path / "labpano.mp4"
        video_path.write_bytes(
            _write_camm_mp4(self.VIDEO, "Labpano", A_UNIX_TIME + 600)
        )
        gpx_path = tmp_path / "other.gpx"
        _write_gpx(gpx_path, _gpx_track(gpx_start, 20))
        return video_path, gpx_path

    def test_extract_rejects_gpx_from_days_before(self, tmp_path: Path):
        video_path, gpx_path = self._write_video_and_gpx(
            tmp_path, A_UNIX_TIME - 3 * 24 * 3600
        )
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError):
            GPXVideoExtractor(video_path, gpx_path).extract()

    def test_next_source_gets_its_turn(self, tmp_path: Path):
        """The GPX misses the video, which says nothing about the video itself."""
        video_path, gpx_path = self._write_video_and_gpx(
            tmp_path, A_UNIX_TIME - 3 * 24 * 3600
        )
        options = [
            SourceOption(
                SourceType.GPX,
                num_processes=0,
                source_path=SourcePathOption(source_path=gpx_path),
            ),
            SourceOption(SourceType.NATIVE, num_processes=0),
        ]

        [metadata] = factory.process([video_path], options)

        assert isinstance(metadata, types.VideoMetadata)
        assert [p.time for p in metadata.points] == [p.time for p in self.VIDEO]


def _camm_exiftool_xml(
    make: str, meta_format: str = "camm", format_tag: str = "MetaFormat"
) -> ET.ElementTree:
    """
    ExifTool XML for a CAMM track, trimmed from a PanoX V2 capture.

    ExifTool reports the format of a camera's CAMM track, under a meta
    handler, as MetaFormat, and that of the CAMM tracks mapillary_tools
    writes, under a camm handler, as OtherFormat.
    """
    xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:QuickTime='http://ns.exiftool.org/QuickTime/QuickTime/1.0/'
 xmlns:Track1='http://ns.exiftool.org/QuickTime/Track1/1.0/'
 xmlns:UserData='http://ns.exiftool.org/QuickTime/UserData/1.0/'>
 <QuickTime:CreateDate>2024:01:18 10:43:57</QuickTime:CreateDate>
 <Track1:{format_tag}>{meta_format}</Track1:{format_tag}>
 <Track1:SampleTime>0</Track1:SampleTime>
 <Track1:SampleDuration>0</Track1:SampleDuration>
 <Track1:GPSDateTime>2024:01:18 10:41:01.600768Z</Track1:GPSDateTime>
 <Track1:GPSMeasureMode>3</Track1:GPSMeasureMode>
 <Track1:GPSLatitude>47.36061891</Track1:GPSLatitude>
 <Track1:GPSLongitude>8.52077651</Track1:GPSLongitude>
 <Track1:GPSAltitude>448.905395507812</Track1:GPSAltitude>
 <UserData:Make>{make}</UserData:Make>
 <UserData:Model>PanoX V2</UserData:Model>
</rdf:Description>
</rdf:RDF>
"""
    root = ET.fromstring(xml)
    desc = root.find("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description")
    assert desc is not None
    return ET.ElementTree(desc)


class TestExifToolAgreesWithNativeParser:
    """
    ExifTool converts CAMM GPS time by the epoch difference alone, so it
    reads 18s (the leap seconds since 1980) later than the native parser.
    The native reading is the right one: in the PanoX V2 capture this is taken
    from, the last GPS sample reads 0.4s before the mvhd creation time, stamped
    when the file is finalized, where ExifTool's reading of it would be 17.6s
    after.
    """

    # 2024-01-18T10:41:01.600768Z, as ExifTool renders it
    EXIFTOOL_TIME = 1705574461.600768
    NATIVE_TIME = EXIFTOOL_TIME - 18

    def _first_epoch_time(self, xml: ET.ElementTree) -> float | None:
        track = ExifToolReadVideo(xml).extract_gps_track()
        return T.cast(telemetry.GPSPoint, track[0]).epoch_time

    @pytest.mark.parametrize(
        "make, meta_format",
        [
            ("Labpano", "camm"),
            ("Labpano Technology Co.,Ltd", "camm"),
            ("Labpano", "CAMM"),
            ("Labpano", " camm "),
        ],
    )
    def test_gps_time_camm_track_is_leap_corrected(self, make: str, meta_format: str):
        epoch_time = self._first_epoch_time(_camm_exiftool_xml(make, meta_format))
        assert epoch_time == pytest.approx(self.NATIVE_TIME, abs=1e-3)

    @pytest.mark.parametrize(
        "make, meta_format", [("Insta360", "camm"), ("Labpano", "gpmd"), ("", "camm")]
    )
    def test_other_tracks_are_left_alone(self, make: str, meta_format: str):
        epoch_time = self._first_epoch_time(_camm_exiftool_xml(make, meta_format))
        assert epoch_time == pytest.approx(self.EXIFTOOL_TIME, abs=1e-3)

    def test_camm_tracks_written_by_mapillary_tools_are_left_alone(self):
        """They hold Unix time, which ExifTool reads as is."""
        xml = _camm_exiftool_xml("Labpano", format_tag="OtherFormat")
        epoch_time = self._first_epoch_time(xml)
        assert epoch_time == pytest.approx(self.EXIFTOOL_TIME, abs=1e-3)

    @pytest.mark.skipif(shutil.which("exiftool") is None, reason="needs ExifTool")
    def test_real_exiftool_reads_our_output_as_written(self, tmp_path: Path):
        video_path = tmp_path / "labpano.mp4"
        video_path.write_bytes(
            _write_camm_mp4(_unix_track(), "Labpano", A_UNIX_TIME + 600)
        )

        xml = ExiftoolRunner(T.cast(str, shutil.which("exiftool"))).extract_xml(
            [video_path]
        )
        [rdf] = exiftool_read.index_rdf_description_by_path_from_xml_element(
            ET.fromstring(xml)
        ).values()
        track = ExifToolReadVideo(ET.ElementTree(rdf)).extract_gps_track()

        epoch_times = [T.cast(telemetry.GPSPoint, p).epoch_time for p in track]
        assert epoch_times == pytest.approx(UNIX_TIMES, abs=1e-3)


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
