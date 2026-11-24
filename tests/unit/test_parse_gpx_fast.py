# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
The fast GPX reader must read whatever gpxpy reads as gpxpy reads it, and
reject whatever gpxpy rejects with the error that gpxpy raises
"""

from __future__ import annotations

import io
import random
from pathlib import Path

import gpxpy
import gpxpy.gpx
import gpxpy.gpxfield
import gpxpy.parser
import pytest

from mapillary_tools import geo
from mapillary_tools.geotag import utils as geotag_utils

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data"

GPX_11 = ' xmlns="http://www.topografix.com/GPX/1/1"'
GPX_10 = ' xmlns="http://www.topografix.com/GPX/1/0"'


def _gpx(body: str, version: str = "1.1", namespaces: str = GPX_11) -> str:
    version_attribute = f' version="{version}"' if version else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<gpx{version_attribute}{namespaces} creator="test">\n{body}\n</gpx>\n'
    )


def _trkpt(
    children: str = "<time>2025-01-01T00:00:00Z</time>",
    attributes: str = 'lat="37.7749" lon="-122.4194"',
) -> str:
    return f"<trkpt {attributes}>{children}</trkpt>"


def _trk(*trkpts: str) -> str:
    return "<trk><trkseg>" + "".join(trkpts) + "</trkseg></trk>"


def _assert_read_as_gpxpy_reads(text: str) -> geotag_utils._ParsedGPX:
    expected = geotag_utils._parse_gpx_with_gpxpy(text)
    # Read by the fast reader itself, not by gpxpy after it gave up
    assert geotag_utils._parse_gpx_fast(text) == expected
    assert geotag_utils._parse_gpx_file(io.StringIO(text)) == expected
    return expected


def _assert_rejected_as_gpxpy_rejects(text: str) -> None:
    with pytest.raises(Exception) as gpxpy_error:
        geotag_utils._parse_gpx_with_gpxpy(text)
    with pytest.raises(Exception):
        geotag_utils._parse_gpx_fast(text)
    # The fast reader raises what gpxpy raised, or leaves the file to gpxpy
    with pytest.raises(gpxpy_error.type) as error:
        geotag_utils._parse_gpx_file(io.StringIO(text))
    assert str(error.value) == str(gpxpy_error.value)


TIMES = [
    "2025-01-01T00:00:00Z",
    "2023-10-30T01:07:30.170Z",
    "2023-10-30T01:07:30.1Z",
    "2023-10-30T01:07:30.123456Z",
    # gpxpy reads microseconds, and cuts the rest
    "2023-10-30T01:07:30.1234567Z",
    "2023-10-30T01:07:30.999999999999999Z",
    "2023-10-30T01:07:30.9999999999999999Z",
    "2020-1-1T0:0:0Z",
    "2020-01-01 00:00:00Z",
    # Local times
    "2020-01-01T00:00:00",
    "2020-07-01T12:30:00.5",
    "2020-01-01T00:00:00+02:00",
    "2020-01-01T00:00:00-0130",
    "2020-01-01T00:00:00−05:00",
    "2020-01-01T00:00:00+05",
    "2020-02-29T12:00:00Z",
    "1969-12-31T23:59:59.5Z",
    "1900-01-01T00:00:00Z",
    "0001-01-01T00:00:00Z",
    "9999-12-31T23:59:59.999999Z",
    "2020-01-01T00:00:00Z\n",
    "2020-01-01T00:00:00.000Z",
    # Times gpxpy does not read
    "2021-02-29T12:00:00Z",
    "2020-02-30T00:00:00Z",
    "2020-01-01T24:00:00Z",
    "2020-01-01T23:60:00Z",
    "2020-01-01T23:59:60Z",
    "2020-13-01T00:00:00Z",
    "0000-01-01T00:00:00Z",
    " 2020-01-01T00:00:00Z",
    "\n  2020-01-01T00:00:00Z\n  ",
    "2020-01-01T00:00:00z",
    "2020-01-01",
    "2020-01-01T00:00Z",
    "2020-01-01T00:00:00.Z",
    "2020-01-01T00:00:00,5Z",
    "２０２０-01-01T00:00:00Z",
    "garbage",
]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(_gpx(_trk(_trkpt())), id="one point"),
        pytest.param(
            _gpx(_trk(*(_trkpt(f"<time>{time}</time>") for time in TIMES))),
            id="times",
        ),
        pytest.param(
            _gpx(_trk(_trkpt("<time></time>"), _trkpt("<time/>"), _trkpt(""))),
            id="no times",
        ),
        pytest.param(
            _gpx(
                _trk(
                    _trkpt(
                        "<ele>1</ele><ele>bad</ele>"
                        "<time>2025-01-01T00:00:00Z</time><time>bad</time>"
                        "<sat>3</sat><sat>bad</sat><fix>2d</fix><fix>bad</fix>"
                    ),
                    _trkpt(
                        "<ele/><ele>2</ele><time/><time>2025-01-01T00:00:00Z</time>"
                    ),
                )
            ),
            id="first of each child",
        ),
        pytest.param(
            _gpx(
                _trk(
                    _trkpt(
                        "<ele> 12.5\n</ele><sat>\t7 </sat><hdop>1e3</hdop>"
                        "<vdop>nan</vdop><pdop>-inf</pdop><magvar>1_0</magvar>"
                        "<time>2025-01-01T00:00:00Z</time>",
                        attributes='lat=" 1.5 " lon="\n-2"',
                    )
                )
            ),
            id="numbers as float() and int() read them",
        ),
        pytest.param(
            _gpx(
                _trk(
                    _trkpt(
                        "<ele/><magvar/><geoidheight/><sat/><hdop/><vdop/><pdop/>"
                        "<ageofdgpsdata/><dgpsid/><fix/><time>2025-01-01T00:00:00Z</time>"
                    )
                )
            ),
            id="empty children",
        ),
        pytest.param(
            _gpx(
                _trk(
                    _trkpt(
                        "<ele>1</ele><time>2025-01-01T00:00:00Z</time><magvar>2</magvar>"
                        "<geoidheight>3</geoidheight><name>n</name><cmt>c</cmt>"
                        "<desc>d</desc><src>s</src>"
                        '<link href="http://example.com"><text>t</text><type>y</type></link>'
                        "<sym>s</sym><type>t</type><fix>dgps</fix><sat>4</sat>"
                        "<hdop>5</hdop><vdop>6</vdop><pdop>7</pdop>"
                        "<ageofdgpsdata>8</ageofdgpsdata><dgpsid>9</dgpsid>"
                        "<extensions><hr>120</hr></extensions>"
                        "<speed>not checked in GPX 1.1</speed><course>x</course>"
                    )
                )
            ),
            id="GPX 1.1 fields",
        ),
        pytest.param(
            _gpx(
                _trk(
                    _trkpt(
                        "<ele>1</ele><time>2025-01-01T00:00:00Z</time>"
                        "<course>2</course><speed>3</speed><url>u</url>"
                        "<urlname>n</urlname><fix>none</fix><fix>bad</fix>"
                    ),
                    _trkpt("<course/><speed>\n4\n</speed><fix>3</fix>"),
                ),
                version="1.0",
                namespaces=GPX_10,
            ),
            id="GPX 1.0 fields",
        ),
        pytest.param(
            _gpx(_trk(_trkpt("<speed>1</speed>")), version="", namespaces=""),
            id="no version",
        ),
        pytest.param("\ufeff" + _gpx(_trk(_trkpt())), id="byte order mark"),
        pytest.param(
            _gpx(
                "<trk><trkseg/></trk>"
                f"<trk><name>a</name><number>2</number><trkseg>{_trkpt()}</trkseg>"
                "<trkseg><extensions/></trkseg>"
                f"<trkseg>{_trkpt()}{_trkpt('')}</trkseg></trk>"
            ),
            id="tracks and segments",
        ),
        pytest.param(
            _gpx(
                f"<trk>{_trkpt()}<trkseg>{_trkpt()}<other>{_trkpt()}</other></trkseg></trk>"
                f"{_trkpt()}<rte><trkseg>{_trkpt()}</trkseg></rte>"
            ),
            id="points that are not in a track segment",
        ),
        pytest.param(
            _gpx(
                '<wpt lat="1" lon="2"><ele>3</ele></wpt>'
                '<rte><rtept lat="1" lon="2"/></rte>' + _trk(_trkpt())
            ),
            id="routes and waypoints",
        ),
        pytest.param(
            _gpx(
                "<metadata><name>m</name><time>bad</time>"
                '<bounds minlat="1" minlon="2" maxlat="3" maxlon="4"/></metadata>'
                + _trk(_trkpt())
            ),
            id="metadata",
        ),
        pytest.param(
            _gpx(
                _trk(_trkpt())
                .replace("<trk>", "<gpx:trk>")
                .replace("</trk>", "</gpx:trk>"),
                namespaces=' xmlns:gpx="http://www.topografix.com/GPX/1/1"',
            ),
            id="prefixed namespace",
        ),
        pytest.param(
            _gpx(
                _trk(_trkpt()).replace("<trk>", f"<trk{GPX_11}>"),
                namespaces="",
            ),
            id="default namespace declared in a track",
        ),
        pytest.param(
            _gpx(_trk(_trkpt()).replace("<trk>", f"<trk{GPX_11}>") + _trk(_trkpt())),
            id="default namespace declared again in a track",
        ),
        pytest.param(
            _gpx(
                _trk(
                    _trkpt(
                        '<ele xmlns="http://example.com">bad</ele><!-- comment -->'
                        "<time><![CDATA[2025-01-01T00:00:00Z]]></time>"
                    )
                ),
                namespaces=GPX_11
                + ' xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1"',
            ),
            id="other namespaces, comments and CDATA",
        ),
        pytest.param(
            _gpx(_trk(_trkpt())).replace("<gpx", "<track").replace("</gpx", "</track"),
            # gpxpy 1.6 reads it; should a later gpxpy reject it, this fails
            id="root element other than gpx",
        ),
    ],
)
def test_read_as_gpxpy_reads(text: str):
    _assert_read_as_gpxpy_reads(text)


def test_read_as_gpxpy_reads_counts():
    parsed = _assert_read_as_gpxpy_reads(
        _gpx(
            '<wpt lat="1" lon="2"/>'
            + _trk(_trkpt(), _trkpt(""), _trkpt("<time>bad</time>"))
            + _trk()
        )
    )
    assert parsed.num_points == 3
    assert [len(track) for track in parsed.tracks] == [1, 0]
    assert parsed.has_routes_or_waypoints


@pytest.mark.parametrize(
    "path",
    sorted((FIXTURE_DIR / "gpx").glob("*.gpx")),
    ids=lambda path: path.name,
)
def test_read_files_as_gpxpy_reads(path: Path):
    _assert_read_as_gpxpy_reads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(_gpx(_trk(_trkpt(attributes='lon="1"'))), id="no lat"),
        pytest.param(_gpx(_trk(_trkpt(attributes='lat="1"'))), id="no lon"),
        pytest.param(_gpx(_trk(_trkpt(attributes='lat="" lon="1"'))), id="empty lat"),
        pytest.param(_gpx(_trk(_trkpt(attributes='lat="1" lon="x"'))), id="bad lon"),
        pytest.param(_gpx(_trk(_trkpt("<ele>bad</ele>"))), id="bad ele"),
        pytest.param(_gpx(_trk(_trkpt("<ele> </ele>"))), id="blank ele"),
        pytest.param(_gpx(_trk(_trkpt("<ele>1,5</ele>"))), id="decimal comma"),
        pytest.param(_gpx(_trk(_trkpt("<sat>1.5</sat>"))), id="bad sat"),
        pytest.param(_gpx(_trk(_trkpt("<dgpsid>x</dgpsid>"))), id="bad dgpsid"),
        pytest.param(_gpx(_trk(_trkpt("<hdop>x</hdop>"))), id="bad hdop"),
        pytest.param(_gpx(_trk(_trkpt("<fix>4d</fix>"))), id="bad fix"),
        pytest.param(_gpx(_trk(_trkpt("<fix> 3d</fix>"))), id="fix with a space"),
        pytest.param(
            _gpx(_trk(_trkpt("<speed>x</speed>")), version="1.0", namespaces=GPX_10),
            id="bad speed in GPX 1.0",
        ),
        pytest.param(
            _gpx(_trk(_trkpt("<course>x</course>")), version="1.0", namespaces=GPX_10),
            id="bad course in GPX 1.0",
        ),
        pytest.param(
            _gpx(_trk(_trkpt(), _trkpt("", attributes='lat="1"'))),
            id="a point without a time and lon",
        ),
        pytest.param(
            _gpx('<wpt lat="1" lon="2"><ele>x</ele></wpt>' + _trk(_trkpt())),
            id="bad waypoint",
        ),
        pytest.param(
            _gpx('<rte><rtept lat="x" lon="2"/></rte>' + _trk(_trkpt())),
            id="bad route point",
        ),
        pytest.param(
            _gpx("<trk><number>x</number><trkseg/></trk>" + _trk(_trkpt())),
            id="bad track number",
        ),
        pytest.param(
            _gpx(
                '<metadata><bounds minlat="x" minlon="2" maxlat="3" maxlon="4"/></metadata>'
                + _trk(_trkpt())
            ),
            id="bad bounds",
        ),
        pytest.param(
            _gpx(_trk(_trkpt("<speed>x</speed>")), version="", namespaces=""),
            id="bad speed without a version, as in GPX 1.0",
        ),
        pytest.param(
            _gpx(_trk(_trkpt("<speed>x</speed>")), version="1.1 "),
            id="bad speed in a version other than 1.1, as in GPX 1.0",
        ),
        pytest.param(_gpx(_trk(_trkpt()))[:-20], id="cut XML"),
        pytest.param("", id="empty"),
    ],
)
def test_rejected_as_gpxpy_rejects(text: str):
    _assert_rejected_as_gpxpy_rejects(text)


@pytest.mark.parametrize("feed_size", [1, 7, 64])
@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            _gpx(
                "<metadata><name>Ünïcødé ☃ 雪</name></metadata>"
                + _trk(
                    _trkpt(
                        "<name>☃</name><ele>1</ele><time>2025-01-01T00:00:00Z</time>"
                    ),
                    _trkpt("<desc>雪</desc><time>2025-01-01T00:00:01.5Z</time>"),
                )
            ),
            id="not ASCII",
        ),
        pytest.param(
            _gpx(
                "<metadata><name>☃</name></metadata>"
                + _trk(_trkpt()).replace("<trk>", f"<trk{GPX_11}>")
                + _trk(_trkpt()),
                namespaces="",
            ),
            id="default namespace declared in a track",
        ),
        # Expat holds back what follows a token much longer than a piece
        pytest.param(
            _gpx(_trk(_trkpt(), f"<!--{'x' * 10_000}-->", _trkpt(), _trkpt())),
            id="long comment between track points",
        ),
        pytest.param(
            _gpx(
                _trk(
                    _trkpt(),
                    _trkpt(f"<!--{'x' * 10_000}--><time>2025-01-01T00:00:01Z</time>"),
                )
            ),
            id="long comment in the last track point",
        ),
        pytest.param(
            _gpx(
                _trk(
                    _trkpt(),
                    _trkpt(attributes=f'lat="1" lon="2" name="{"x" * 10_000}"'),
                )
            ),
            id="long attribute in the last track point",
        ),
    ],
)
def test_read_in_pieces(text: str, feed_size: int, monkeypatch):
    expected = geotag_utils._parse_gpx_with_gpxpy(text)
    monkeypatch.setattr(geotag_utils, "_FEED_SIZE", feed_size)
    assert geotag_utils._parse_gpx_fast(text) == expected


@pytest.mark.parametrize("feed_size", [1, 7, 64, geotag_utils._FEED_SIZE])
@pytest.mark.parametrize(
    "text",
    [
        pytest.param(_gpx(_trk(_trkpt()))[:-20], id="cut XML"),
        pytest.param("", id="empty"),
        pytest.param("\n \n", id="blank"),
        pytest.param(_gpx(_trk(_trkpt()) + "</trk>"), id="mismatched tag"),
        pytest.param(_gpx(_trk(_trkpt(attributes="lat=1 lon=2"))), id="bad token"),
        pytest.param(
            _gpx(_trk(_trkpt(attributes='lat="1" lat="2" lon="3"'))),
            id="duplicate attribute",
        ),
        pytest.param(
            _gpx("<name>&nbsp;</name>" + _trk(_trkpt())), id="undefined entity"
        ),
        pytest.param(_gpx(_trk(_trkpt())) + "<gpx/>", id="junk after the root"),
        pytest.param(_gpx("<name><![CDATA[x</name>"), id="CDATA cut short"),
        pytest.param(
            _gpx("<metadata><name>Ünïcødé ☃ 雪</name></metadata>\n<trk>☃</gpx>"),
            id="not ASCII before the error",
        ),
        pytest.param(
            '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk></gpx>',
            id="error after the default namespace on the same line",
        ),
        pytest.param("\ufeff" + _gpx("<trk>"), id="BOM"),
        pytest.param(" " + _gpx(_trk(_trkpt())), id="text before the declaration"),
        pytest.param(_gpx("<trk>\x00</trk>"), id="NUL"),
    ],
)
def test_invalid_xml_rejected_as_gpxpy_rejects(text: str, feed_size: int, monkeypatch):
    with pytest.raises(gpxpy.gpx.GPXXMLSyntaxException) as gpxpy_error:
        geotag_utils._parse_gpx_with_gpxpy(text)
    monkeypatch.setattr(geotag_utils, "_FEED_SIZE", feed_size)

    # Without gpxpy parsing it again
    def fail(xml_or_file):
        raise AssertionError("parsed again")

    monkeypatch.setattr(geotag_utils, "_parse_gpx_with_gpxpy", fail)
    with pytest.raises(gpxpy.gpx.GPXXMLSyntaxException) as error:
        geotag_utils._parse_gpx_file(io.StringIO(text))
    assert type(error.value) is gpxpy.gpx.GPXXMLSyntaxException
    assert str(error.value) == str(gpxpy_error.value)
    assert type(error.value.__cause__) is type(gpxpy_error.value.__cause__)
    assert str(error.value.__cause__) == str(gpxpy_error.value.__cause__)


def test_read_by_gpxpy_if_the_fast_reader_fails(monkeypatch):
    text = _gpx(_trk(_trkpt(), _trkpt("<ele>1</ele><time>2025-01-01T00:00:01Z</time>")))
    expected = geotag_utils._parse_gpx_with_gpxpy(text)

    def fail(text: str):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(geotag_utils, "_parse_gpx_fast", fail)
    assert geotag_utils._parse_gpx_file(io.StringIO(text)) == expected


def test_not_read_fast_if_gpxpy_uses_lxml(monkeypatch):
    monkeypatch.setattr(gpxpy.parser, "library", lambda: "LXML")
    with pytest.raises(geotag_utils._IrregularGPXError):
        geotag_utils._parse_gpx_fast(_gpx(_trk(_trkpt())))


def test_track_point_checks():
    assert geotag_utils._TRACK_POINT_CHECKS_10 is not None
    assert geotag_utils._TRACK_POINT_CHECKS_11 is not None
    assert "speed" in geotag_utils._TRACK_POINT_CHECKS_10
    assert "speed" not in geotag_utils._TRACK_POINT_CHECKS_11


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(
            gpxpy.gpxfield.GPXComplexField("bounds", classs=gpxpy.gpx.GPXBounds),
            id="complex field",
        ),
        pytest.param(
            gpxpy.gpxfield.GPXField(
                "speed", type=gpxpy.gpxfield.FLOAT_TYPE, mandatory=True
            ),
            id="mandatory child",
        ),
        pytest.param(
            gpxpy.gpxfield.GPXField(
                "speed", attribute="speed", type=gpxpy.gpxfield.FLOAT_TYPE
            ),
            id="checked attribute",
        ),
        pytest.param(
            gpxpy.gpxfield.GPXField(
                "speed", type=gpxpy.gpxfield.FLOAT_TYPE, possible=("1",)
            ),
            id="converted and checked",
        ),
        pytest.param(
            gpxpy.gpxfield.GPXField("start", type=gpxpy.gpxfield.TIME_TYPE),
            id="another time",
        ),
    ],
)
def test_track_point_checks_of_unknown_fields(extra):
    fields = list(gpxpy.gpx.GPXTrackPoint.gpx_11_fields)
    assert geotag_utils._track_point_checks(fields) is not None
    assert geotag_utils._track_point_checks([*fields, extra]) is None
    # Converted in a container element
    assert (
        geotag_utils._track_point_checks(
            [
                *fields,
                "container",
                gpxpy.gpxfield.GPXField("speed", type=gpxpy.gpxfield.FLOAT_TYPE),
                "/container",
            ]
        )
        is None
    )


def _gpxpy_unix_time(text: str) -> float | None:
    time = gpxpy.gpxfield.TIME_TYPE.from_string(text)
    return None if time is None else geo.as_unix_time(time)


@pytest.mark.parametrize("text", TIMES)
def test_unix_time_from_gpx_time(text: str):
    assert geotag_utils._unix_time_from_gpx_time(text, {}) == _gpxpy_unix_time(text)


def test_unix_time_from_random_gpx_times():
    rng = random.Random(0)
    seconds_by_minute: dict[str, int | None] = {}
    for _ in range(5000):
        fraction = "".join(rng.choice("0123456789") for _ in range(rng.randint(0, 7)))
        text = (
            f"{rng.randint(1, 9999):04}-{rng.randint(1, 12):02}-{rng.randint(1, 31):02}"
            f"T{rng.randint(0, 24):02}:{rng.randint(0, 60):02}:{rng.randint(0, 60):02}"
            + (f".{fraction}" if fraction else "")
            + "Z"
        )
        assert geotag_utils._unix_time_from_gpx_time(
            text, seconds_by_minute
        ) == _gpxpy_unix_time(text), text


def test_track_points_are_freed_once_read(monkeypatch):
    """
    Each track point is taken out of the tree once read, rather than kept
    there until the whole file is parsed, also when a piece of the text holds
    hundreds of them
    """
    import weakref

    num_points = 2_500
    text = _gpx(
        _trk(
            *(
                _trkpt(f"<time>2025-01-01T00:{i // 60:02d}:{i % 60:02d}Z</time>")
                for i in range(num_points)
            )
        )
    )
    # Read in several pieces
    assert 2 * geotag_utils._FEED_SIZE < len(text)
    read: list[weakref.ref] = []
    read_track_point = geotag_utils._read_track_point

    def recording_read_track_point(trkpt, checks, seconds_by_minute):
        # The point read before the one before this one is freed, as were all
        # the points before it when it was read
        if 2 <= len(read):
            assert read[-2]() is None
        read.append(weakref.ref(trkpt))
        return read_track_point(trkpt, checks, seconds_by_minute)

    monkeypatch.setattr(geotag_utils, "_read_track_point", recording_read_track_point)
    assert geotag_utils._parse_gpx_fast(text) == geotag_utils._parse_gpx_with_gpxpy(
        text
    )
    assert len(read) == num_points


_TRACK_OF_60_POINTS = _trk(
    *(
        _trkpt(f"<ele>{i}</ele><time>2025-01-01T00:00:{i:02d}Z</time>")
        for i in range(60)
    )
)


@pytest.mark.parametrize(
    "text, valid",
    [
        pytest.param(
            _gpx(
                "<metadata><name>track</name></metadata>"
                + _TRACK_OF_60_POINTS
                + "<wpt lat='1' lon='2'><name>w</name></wpt>"
            ),
            True,
            id="valid",
        ),
        pytest.param(
            _gpx(_TRACK_OF_60_POINTS + "<name>a & b</name>"),
            False,
            id="invalid XML after the track points",
        ),
    ],
)
def test_reading_makes_no_reference_cycles(text: str, valid: bool):
    """
    Which the garbage collector, paused while a GPX file is read, would have
    to free (see utils.gc_paused())
    """
    import gc

    gc.collect()
    enabled = gc.isenabled()
    gc.disable()
    try:
        # By the fast reader itself, which raises rather than give the file to
        # gpxpy
        if valid:
            parsed = geotag_utils._parse_gpx_fast(text)
            assert parsed.num_points == 60
            del parsed
        else:
            try:
                geotag_utils._parse_gpx_fast(text)
            except gpxpy.gpx.GPXXMLSyntaxException:
                pass
            else:
                raise AssertionError("invalid XML read")
        assert gc.collect() == 0
    finally:
        if enabled:
            gc.enable()
