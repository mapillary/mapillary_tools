# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
A GPX file without a track point whose time can be read fails, saying why,
and one with only some is warned of: gpxpy reads no time for a point whose
time it cannot read, and says nothing of it. Points without a <time> are
left out without a word, as GPX allows them
"""

from __future__ import annotations

import datetime
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

import gpxpy
import pytest
from mapillary_tools import exceptions, geo, types
from mapillary_tools.geotag import geotag_videos_from_gpx, utils
from mapillary_tools.geotag.geotag_images_from_gpx_file import GeotagImagesFromGPXFile
from mapillary_tools.geotag.options import SourcePathOption
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor

# 2026-08-12T06:32:05Z
START = 1786516325.0


def _gpx(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"{body}</gpx>\n"
    )


def _track(*times: str | None) -> str:
    """A GPX file of a track of a point at each time, written as is"""
    points = "".join(
        f'<trkpt lat="{52 + idx / 1000}" lon="13.0">'
        + ("" if time is None else f"<time>{time}</time>")
        + "</trkpt>\n"
        for idx, time in enumerate(times)
    )
    return _gpx(f"<trk><trkseg>\n{points}</trkseg></trk>\n")


def _times(num: int, form: str = "{}.000Z") -> list[str]:
    """The times of **num** points a second apart from START, in **form**"""
    return [
        form.format(
            datetime.datetime.fromtimestamp(START + idx, datetime.timezone.utc)
            .replace(tzinfo=None)
            .isoformat()
        )
        for idx in range(num)
    ]


@pytest.fixture
def gpx(tmp_path: Path, monkeypatch) -> Path:
    """The path of a GPX file, with no GPX file parsed or warned of before"""
    monkeypatch.setattr(utils, "_PARSED_GPX", type(utils._PARSED_GPX)())
    monkeypatch.setattr(utils, "_WARNED", set())
    return tmp_path / "X.gpx"


def _error(gpx: Path) -> str:
    with pytest.raises(exceptions.MapillaryInvalidGPXError) as ex:
        utils.read_gpx_tracks(gpx)
    return str(ex.value)


class TestNoTrackPointWithATime:
    def test_the_user_form_with_two_fractions(self, gpx: Path):
        gpx.write_text(_track(*_times(60, "{}.000.000Z")))

        assert _error(gpx) == (
            "X.gpx has no track point with a time that can be read: "
            "'2026-08-12T06:32:05.000.000Z' is not a GPX time, "
            "which looks like 2026-08-12T06:32:05.000Z"
        )

    def test_track_points_without_a_time(self, gpx: Path):
        gpx.write_text(_track(None, None, None))

        assert _error(gpx) == (
            "X.gpx has no track point with a time that can be read: "
            "its track points have no <time>"
        )

    @pytest.mark.parametrize(
        "time",
        [
            "",
            # gpxpy reads the text as it is
            " 2026-08-12T06:32:05Z",
            "2026-08-12",
            "2026-13-12T06:32:05Z",
        ],
    )
    def test_other_times_that_cannot_be_read(self, gpx: Path, time: str):
        gpx.write_text(_track(time, time))

        assert _error(gpx).endswith(
            f": {time!r} is not a GPX time, which looks like 2026-08-12T06:32:05.000Z"
        )

    def test_the_first_time_of_a_track_point_is_shown(self, gpx: Path):
        """Not that of the metadata, or of a waypoint, which are not read"""
        gpx.write_text(
            _gpx(
                "<metadata><time>metadata</time></metadata>\n"
                '<wpt lat="52.0" lon="13.0"><time>waypoint</time></wpt>\n'
                "<trk><trkseg>\n"
                '<trkpt lat="52.0" lon="13.0"></trkpt>\n'
                '<trkpt lat="52.0" lon="13.0"><time>first</time></trkpt>\n'
                '<trkpt lat="52.0" lon="13.0"><time>second</time></trkpt>\n'
                "</trkseg></trk>\n"
            )
        )

        assert "has no track point with a time that can be read: 'first'" in _error(gpx)

    @pytest.mark.parametrize(
        "declaration",
        ['<?xml version="1.0"?>', '<?xml version="1.0" encoding="ISO-8859-1"?>'],
    )
    def test_a_file_in_another_encoding(self, gpx: Path, declaration: str):
        """
        Read again as gpxpy reads it, as UTF-8, where a byte that is not
        UTF-8 only spoils a name
        """
        content = (
            _track(*_times(2, "{}.000.000Z"))
            .replace('<?xml version="1.0" encoding="UTF-8"?>', declaration)
            .replace("<trk>", "<trk><name>Caf\u00e9</name>")
        )
        gpx.write_bytes(content.encode("latin-1"))

        assert _error(gpx).endswith(
            ": '2026-08-12T06:32:05.000.000Z' is not a GPX time, "
            "which looks like 2026-08-12T06:32:05.000Z"
        )

    def test_a_time_with_a_second_fraction_is_not_guessed(self, gpx: Path):
        gpx.write_text(_track("2026-08-12T06:32:05.123.456Z"))

        assert "'2026-08-12T06:32:05.123.456Z' is not a GPX time" in _error(gpx)

    @pytest.mark.parametrize(
        "error",
        [
            ET.ParseError("encoding specified in XML declaration is incorrect"),
            LookupError("unknown encoding: foo"),
            FileNotFoundError(2, "No such file or directory"),
        ],
    )
    def test_without_the_reason_if_the_file_cannot_be_read_again(
        self, gpx: Path, monkeypatch, error: Exception
    ):
        """As when gpxpy decoded it otherwise, or parsed it with lxml"""
        gpx.write_text(_track(*_times(2, "{}.000.000Z")))

        def unreadable(gpx_file: Path) -> utils._UnreadableTimes:
            raise error

        monkeypatch.setattr(utils, "_read_unreadable_times", unreadable)

        assert _error(gpx) == "X.gpx has no track point with a time that can be read"

    @pytest.mark.parametrize(
        "body",
        [
            '<wpt lat="52.0" lon="13.0"><time>2026-08-12T06:32:05Z</time></wpt>\n',
            '<rte><rtept lat="52.0" lon="13.0"><time>2026-08-12T06:32:05Z</time>'
            "</rtept></rte>\n",
        ],
    )
    def test_only_routes_or_waypoints(self, gpx: Path, body: str):
        gpx.write_text(_gpx(body))

        assert _error(gpx) == (
            "X.gpx has no track points; routes and waypoints are not read"
        )

    @pytest.mark.parametrize(
        "content",
        [
            _gpx(""),
            _gpx("<trk><trkseg></trkseg></trk>\n"),
            # gpxpy reads any XML document
            '<?xml version="1.0"?><kml/>',
        ],
    )
    def test_no_track_points(self, gpx: Path, content: str):
        gpx.write_text(content)

        assert _error(gpx) == "X.gpx has no track points"

    def test_the_error_is_kept_as_the_tracks_are(self, gpx: Path, monkeypatch):
        gpx.write_text(_track(*_times(2, "{}.000.000Z")))
        parses = []
        parse = gpxpy.parse

        def counting_parse(*args, **kwargs):
            parses.append(1)
            return parse(*args, **kwargs)

        monkeypatch.setattr(gpxpy, "parse", counting_parse)

        assert _error(gpx) == _error(gpx)
        assert len(parses) == 1


class TestSomeTrackPointsWithoutATime:
    def test_half_the_times_cannot_be_read(self, gpx: Path, caplog):
        good = _times(60)
        bad = _times(60, "{}.000.000Z")
        gpx.write_text(_track(*(good[i] if i % 2 == 0 else bad[i] for i in range(60))))

        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                [track] = utils.parse_gpx(gpx)

        assert [p.time for p in track] == [START + i for i in range(0, 60, 2)]
        assert [p.lat for p in track] == [52 + i / 1000 for i in range(0, 60, 2)]
        assert caplog.messages == [
            f"Ignoring 30 of the 60 points in the GPX file {gpx}, "
            "whose times cannot be read (e.g. '2026-08-12T06:32:06.000.000Z')"
        ]

    def test_some_track_points_without_a_time_are_left_out_quietly(
        self, gpx: Path, caplog
    ):
        """
        As ExifTool writes a GPX of a GoPro video: a <time> only on the points
        with a GPS time
        """
        gpx.write_text(
            _track("2026-08-12T06:32:05Z", None, None, "2026-08-12T06:32:06Z", None)
        )

        with caplog.at_level(logging.WARNING):
            [track] = utils.parse_gpx(gpx)

        assert [(p.time, p.lat) for p in track] == [(START, 52.0), (START + 1, 52.003)]
        assert not caplog.messages

    def test_only_the_times_that_cannot_be_read_are_counted(self, gpx: Path, caplog):
        gpx.write_text(
            _track("2026-08-12T06:32:05Z", None, "bad", "2026-08-12T06:32:06Z", None)
        )

        with caplog.at_level(logging.WARNING):
            [track] = utils.parse_gpx(gpx)

        assert [p.time for p in track] == [START, START + 1]
        assert caplog.messages == [
            f"Ignoring 1 of the 5 points in the GPX file {gpx}, "
            "whose times cannot be read (e.g. 'bad')"
        ]

    def test_all_the_points_left_out_if_the_file_cannot_be_read_again(
        self, gpx: Path, caplog, monkeypatch
    ):
        """Whether they have no <time> or one that cannot be read is not known"""
        gpx.write_text(_track("2026-08-12T06:32:05Z", None, "bad"))

        def unreadable(gpx_file: Path) -> utils._UnreadableTimes:
            raise ET.ParseError("not well-formed")

        monkeypatch.setattr(utils, "_read_unreadable_times", unreadable)

        with caplog.at_level(logging.WARNING):
            [track] = utils.parse_gpx(gpx)

        assert [p.time for p in track] == [START]
        assert caplog.messages == [
            f"Ignoring 2 of the 3 points in the GPX file {gpx}, "
            "whose times cannot be read"
        ]

    def test_images_and_videos_warn_once(self, gpx: Path, caplog):
        gpx.write_text(_track("2026-08-12T06:32:05Z", "bad", "2026-08-12T06:32:07Z"))

        with caplog.at_level(logging.WARNING):
            geotag = GeotagImagesFromGPXFile(gpx)
            points = GPXVideoExtractor(gpx.with_suffix(".mp4"), gpx)._read_gpx_points()

        assert geotag.track_error is None
        assert len(geotag.points) == len(points) == 2
        assert len(caplog.messages) == 1, caplog.messages

    def test_the_before_1980_warning_is_unchanged(self, gpx: Path, caplog):
        """It counts the points with a time, of which it leaves some out too"""
        gpx.write_text(
            _track(
                "1970-01-01T00:00:01Z",
                "bad",
                "2026-08-12T06:32:05Z",
                "2026-08-12T06:32:06Z",
            )
        )

        with caplog.at_level(logging.WARNING):
            points = GPXVideoExtractor(gpx.with_suffix(".mp4"), gpx)._read_gpx_points()

        assert [p.time for p in points] == [START, START + 1]
        assert caplog.messages == [
            f"Ignoring 1 of the 4 points in the GPX file {gpx}, "
            "whose times cannot be read (e.g. 'bad')",
            f"Ignoring 1 of the 3 points in the GPX file {gpx}, "
            "which are timestamped before 1980",
        ]


def test_a_valid_gpx_file_is_unchanged(gpx: Path, caplog):
    gpx.write_text(_track(*_times(3)))

    with caplog.at_level(logging.WARNING):
        [track] = utils.parse_gpx(gpx)

    assert [(p.time, p.lat, p.lon) for p in track] == [
        (START, 52.0, 13.0),
        (START + 1, 52.001, 13.0),
        (START + 2, 52.002, 13.0),
    ]
    assert not caplog.messages


class TestEveryPathFails:
    MESSAGE = (
        "X.gpx has no track point with a time that can be read: "
        "'2026-08-12T06:32:05.000.000Z' is not a GPX time"
    )

    def test_images(self, gpx: Path):
        gpx.write_text(_track(*_times(2, "{}.000.000Z")))
        images = [Path("a.jpg"), Path("b.jpg")]

        descs = GeotagImagesFromGPXFile(gpx).to_description(images)

        assert [d.filename for d in descs] == images
        for desc in descs:
            assert isinstance(desc, types.ErrorMetadata)
            assert isinstance(desc.error, exceptions.MapillaryInvalidGPXError)
            assert str(desc.error).startswith(self.MESSAGE)

    def test_a_video(self, gpx: Path):
        """Before its own GPS is read: the video is not read at all"""
        gpx.write_text(_track(*_times(2, "{}.000.000Z")))

        with pytest.raises(exceptions.MapillaryInvalidGPXError, match=self.MESSAGE):
            GPXVideoExtractor(gpx.with_suffix(".mp4"), gpx).extract()

    def test_videos_of_a_file_read_before_the_pool(self, gpx: Path):
        gpx.write_text(_track(*_times(2, "{}.000.000Z")))
        videos = [gpx.with_name("a.mp4"), gpx.with_name("b.mp4")]

        geotag = geotag_videos_from_gpx.GeotagVideosFromGPX(
            source_path=SourcePathOption(source_path=gpx)
        )
        extractors = geotag._generate_video_extractors(videos)

        for extractor in extractors:
            assert isinstance(extractor, GPXVideoExtractor)
            assert isinstance(extractor._tracks, exceptions.MapillaryInvalidGPXError)
            with pytest.raises(exceptions.MapillaryInvalidGPXError, match=self.MESSAGE):
                extractor.extract()


def test_points_are_track_points(gpx: Path):
    """The tracks read are those parse_gpx() returned before"""
    gpx.write_text(_track(*_times(2)))

    [track] = utils.parse_gpx(gpx)

    assert all(isinstance(p, geo.Point) for p in track)
    assert [p.epoch_time for p in track] == [START, START + 1]
