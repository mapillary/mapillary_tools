# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Reading the fixes of NMEA files as receivers log them: before a fix, with
void sentences, and from talkers other than GPS.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

import pynmea2
import pytest
from mapillary_tools.geotag import geotag_images_from_nmea_file
from mapillary_tools.geotag.geotag_images_from_nmea_file import (
    get_lat_lon_time_from_nmea,
)


def _sentence(body: str) -> str:
    return f"${body}*{pynmea2.NMEASentence.checksum(body):02X}"


def _rmc(time: str, date: str = "221222", status: str = "A", talker="GP") -> str:
    return _sentence(
        f"{talker}RMC,{time},{status},3735.30670,N,12220.25810,W,0.0,0.0,{date},,,A"
    )


def _gga(time: str, quality: int = 1, talker="GP", lat="3735.30670") -> str:
    return _sentence(
        f"{talker}GGA,{time},{lat},N,12220.25810,W,{quality},08,1.0,12.5,M,0.0,M,,"
    )


def _read(tmp_path: Path, *lines: str):
    path = tmp_path / "track.nmea"
    # Bytes, so that the line ends are CRLF on every platform: write_text() on
    # Windows would write each "\r\n" as "\r\r\n", an empty line more
    path.write_bytes("".join(f"{line}\r\n" for line in lines).encode("ascii"))
    return [
        (
            datetime.datetime.fromtimestamp(p.time, datetime.timezone.utc).isoformat(),
            round(p.lat, 6),
            round(p.lon, 6),
            p.alt,
        )
        for p in get_lat_lon_time_from_nmea(path)
    ]


def _fix(time: str, date: str = "2022-12-22", lat: float = 37.588445):
    return (f"{date}T{time}+00:00", lat, -122.337635, 12.5)


def test_gps_fixes(tmp_path):
    assert _read(
        tmp_path,
        _rmc("024636.00"),
        _gga("024636.00"),
        _rmc("024637.00"),
        _gga("024637.00"),
    ) == [_fix("02:46:36"), _fix("02:46:37")]


@pytest.mark.parametrize("talker", ["GN", "GL", "GA", "BD"])
def test_any_talker(tmp_path, talker):
    """Receivers of several systems log $GN sentences, which read 0 points"""
    assert _read(
        tmp_path, _rmc("024636.00", talker=talker), _gga("024636.00", talker=talker)
    ) == [_fix("02:46:36")]


def test_one_point_per_time(tmp_path):
    """
    Of the fixes that several talkers log for the same time, the first is
    read, so that no two points share a time
    """
    assert _read(
        tmp_path,
        _rmc("024636.00", talker="GP"),
        _rmc("024636.00", talker="GN"),
        _gga("024636.00", talker="GP"),
        _gga("024636.00", talker="GN", lat="3735.30610"),
        _gga("024637.00", talker="GN", lat="3735.30610"),
        _gga("024637.00", talker="GP"),
    ) == [_fix("02:46:36"), _fix("02:46:37", lat=37.588435)]


def test_sentences_before_the_first_fix_are_skipped(tmp_path, caplog):
    """
    A log that started before its first fix was rejected whole, and gave
    positions at 0, 0
    """
    with caplog.at_level(logging.WARNING):
        assert _read(
            tmp_path,
            # void, with the date of a clock that is not set yet, and empty
            _rmc("000001.00", date="060180", status="V"),
            _sentence("GPRMC,,V,,,,,,,,,,N"),
            # no fix, with and without a time
            _sentence("GPGGA,024635.00,,,,,0,00,99.99,,,,,,"),
            _sentence("GPGGA,,,,,,0,00,,,M,,M,,"),
            _rmc("024636.00"),
            _gga("024636.00"),
        ) == [_fix("02:46:36")]

    # They are not malformed
    assert not caplog.text


def test_a_void_rmc_gives_no_date(tmp_path):
    assert _read(
        tmp_path,
        _rmc("024636.00"),
        _gga("024636.00"),
        _rmc("024637.00", date="060180", status="V"),
        _gga("024637.00"),
    ) == [_fix("02:46:36"), _fix("02:46:37")]


def test_a_cut_off_sentence_is_skipped(tmp_path):
    """The last sentence of a log cut short has no date, and failed the file"""
    assert _read(
        tmp_path, _rmc("024636.00"), _gga("024636.00"), "$GPRMC,024637.00,A,3735.3"
    ) == [_fix("02:46:36")]


def test_gga_before_the_first_rmc_take_its_date(tmp_path):
    assert _read(
        tmp_path,
        _gga("024635.00", lat="3735.30610"),
        _rmc("024636.00"),
        _gga("024636.00"),
    ) == [_fix("02:46:35", lat=37.588435), _fix("02:46:36")]


@pytest.mark.parametrize("gga_first", [True, False])
def test_fixes_across_midnight(tmp_path, gga_first):
    """
    The first fix after midnight, logged before the RMC sentence with its
    date, was dated a day early, a day before the rest of the track
    """
    lines = []
    for time, date in [
        ("235959.00", "211222"),
        ("000000.00", "221222"),
        ("000001.00", "221222"),
    ]:
        if gga_first:
            lines += [_gga(time), _rmc(time, date=date)]
        else:
            lines += [_rmc(time, date=date), _gga(time)]

    assert _read(tmp_path, *lines) == [
        _fix("23:59:59", date="2022-12-21"),
        _fix("00:00:00"),
        _fix("00:00:01"),
    ]


def test_gga_before_the_first_rmc_across_midnight(tmp_path):
    """It took the date of the RMC sentence, a day late"""
    assert _read(
        tmp_path,
        _gga("235959.00", lat="3735.30610"),
        _rmc("000000.00"),
        _gga("000000.00"),
    ) == [_fix("23:59:59", date="2022-12-21", lat=37.588435), _fix("00:00:00")]


def test_a_log_of_another_day_appended(tmp_path):
    """
    Its first fix, logged before its RMC sentence, takes the date of that
    sentence, not that of the fix before it
    """
    assert _read(
        tmp_path,
        _rmc("180000.00", date="211222"),
        _gga("180000.00"),
        _gga("090000.00", lat="3735.30610"),
        _rmc("090000.00", date="241222"),
    ) == [
        _fix("18:00:00", date="2022-12-21"),
        _fix("09:00:00", date="2022-12-24", lat=37.588435),
    ]


def test_a_malformed_sentence_is_skipped_with_a_warning(tmp_path, caplog):
    """One failed the whole file, and every image geotagged from it"""
    bad_checksum = _gga("024636.50", talker="GL")[:-2] + "00"
    with caplog.at_level(logging.WARNING):
        assert _read(
            tmp_path,
            _rmc("024636.00"),
            _gga("024636.00"),
            bad_checksum,
            _rmc("024637.00"),
            _gga("024637.00"),
        ) == [_fix("02:46:36"), _fix("02:46:37")]

    assert "Skipping 1 of the 5 RMC and GGA sentences of the NMEA file" in caplog.text
    assert "on line 3 (checksum does not match: 00 != " in caplog.text
    assert bad_checksum in caplog.text


@pytest.mark.parametrize(
    "malformed",
    [
        # pynmea2 leaves the fields it cannot parse strings
        _gga("0246"),
        _sentence("GPGGA,024636.50,3735.30670,N,12220.25810,W,x,08,1.0,12.5,M,0.0,M,,"),
        _gga("024636.50").replace(",12.5,", ",12.x,"),
        _rmc("024636.50", date="2212x2"),
        # and fails to compute the position from them
        _gga("024636.50", lat="37x5.30670"),
        # junk after the sentence type
        "$GPGGA,\x01\x02",
    ],
)
def test_malformed_fields_are_skipped(tmp_path, caplog, malformed):
    with caplog.at_level(logging.WARNING):
        assert _read(
            tmp_path,
            _rmc("024636.00"),
            _gga("024636.00"),
            malformed,
            _rmc("024637.00"),
            _gga("024637.00"),
        ) == [_fix("02:46:36"), _fix("02:46:37")]

    assert "Skipping 1 of the 5 RMC and GGA sentences" in caplog.text


@pytest.mark.parametrize("gga_first", [True, False])
def test_a_sentence_cut_inside_its_date_is_skipped(tmp_path, caplog, gga_first):
    """
    pynmea2 read the date "2212" of an RMC sentence cut short, the last of a
    log, as 2012-02-02, and the last fix took it: a track of 10 years
    """
    lines = []
    for time, date in [("235959.00", "211222"), ("000000.00", "221222")]:
        if gga_first:
            lines += [_gga(time), _rmc(time, date=date)]
        else:
            lines += [_rmc(time, date=date), _gga(time)]
    if gga_first:
        lines.append(_gga("000001.00"))
    cut = _rmc("000001.00").split(",221222,")[0] + ",2212"

    with caplog.at_level(logging.WARNING):
        assert _read(tmp_path, *lines, cut) == [
            _fix("23:59:59", date="2022-12-21"),
            _fix("00:00:00"),
        ] + ([_fix("00:00:01")] if gga_first else [])

    assert "Skipping 1 of the" in caplog.text
    assert "(malformed datestamp: '2212')" in caplog.text


def test_sentences_cut_short_are_skipped_with_one_warning(tmp_path, caplog):
    lines = []
    for second in range(10):
        lines += [_rmc(f"02463{second}.00"), _gga(f"02463{second}.00")]
    # Every other fix cut short, at another field each time
    for idx in range(1, 20, 4):
        lines[idx] = lines[idx][: 10 + 3 * idx]

    with caplog.at_level(logging.WARNING):
        points = _read(tmp_path, *lines)

    assert [p[0][11:19] for p in points] == [
        f"02:46:3{second}" for second in range(10) if second % 2 == 1
    ]
    assert caplog.text.count("Skipping 5 of the 20 RMC and GGA sentences") == 1


def test_sentences_without_checksums_are_read(tmp_path, caplog):
    """In a log whose sentences carry no checksum, as some converters write"""

    def bare(sentence: str) -> str:
        return sentence.rsplit("*", 1)[0]

    with caplog.at_level(logging.WARNING):
        assert _read(
            tmp_path,
            bare(_rmc("024636.00")),
            bare(_gga("024636.00")),
            bare(_rmc("024637.00")),
            bare(_gga("024637.00")),
        ) == [_fix("02:46:36"), _fix("02:46:37")]

    assert not caplog.text


@pytest.mark.parametrize(
    "cut, error",
    [
        # pynmea2 read these as 2012-02-02 and 00:00:02
        ("$GPRMC,024637.00,A,3735.30670,N,12220.25810,W,0.0,0.0,2212", "datestamp"),
        ("$GPGGA,00002", "timestamp"),
    ],
)
def test_fields_cut_short_without_checksums_are_skipped(tmp_path, caplog, cut, error):
    """Where no sentence has a checksum, a field cut short tells it"""

    def bare(sentence: str) -> str:
        return sentence.rsplit("*", 1)[0]

    with caplog.at_level(logging.WARNING):
        assert _read(
            tmp_path, bare(_rmc("024636.00")), bare(_gga("024636.00")), cut
        ) == [_fix("02:46:36")]

    assert f"(malformed {error}: " in caplog.text


def _bare(sentence: str) -> str:
    """The sentence without its checksum, which is optional"""
    return sentence.rsplit("*", 1)[0]


def _log(seconds: int = 4) -> list[str]:
    lines = []
    for second in range(seconds):
        lines += [_rmc(f"02463{second}.00"), _gga(f"02463{second}.00")]
    return lines


def _fixes(seconds: int = 4) -> list:
    return [_fix(f"02:46:3{second}") for second in range(seconds)]


def test_a_log_with_one_checksum_is_read(tmp_path, caplog):
    """The sentences without one were all taken for cut short: no fix was left"""
    lines = [_bare(line) for line in _log()]
    lines[3] = _log()[3]

    with caplog.at_level(logging.WARNING):
        assert _read(tmp_path, *lines) == _fixes()

    assert not caplog.text


def test_a_log_with_checksums_on_gga_sentences_only_is_read(tmp_path, caplog):
    lines = [line if "GGA," in line else _bare(line) for line in _log()]

    with caplog.at_level(logging.WARNING):
        assert _read(tmp_path, *lines) == _fixes()

    assert not caplog.text


def test_logs_with_and_without_checksums_concatenated_are_read(tmp_path, caplog):
    """The half without checksums was skipped"""
    lines = _log()
    lines = lines[:4] + [_bare(line) for line in lines[4:]]

    with caplog.at_level(logging.WARNING):
        assert _read(tmp_path, *lines) == _fixes()

    assert not caplog.text


@pytest.mark.parametrize(
    "rmc_tail",
    [
        # NMEA 2.0 to 2.2: no mode
        ",,",
        # NMEA 2.3: the mode
        ",,,A",
        # NMEA 4.1: the mode and the navigational status
        ",,,A,V",
    ],
)
def test_complete_sentences_without_checksums_are_read(tmp_path, caplog, rmc_tail):
    rmc = "$GPRMC,024636.00,A,3735.30670,N,12220.25810,W,0.0,0.0,221222" + rmc_tail
    gga = _bare(_gga("024636.00"))

    with caplog.at_level(logging.WARNING):
        assert _read(tmp_path, rmc, gga) == [_fix("02:46:36")]

    assert not caplog.text


@pytest.mark.parametrize(
    "cut, reason",
    [
        # Whole fields, the last of them maybe cut short too
        (
            "$GPRMC,024637.00,A,3735.30670,N,12220.25810,W,0.0,0.0,221222",
            "cut short: 9 of the 11 fields of an RMC sentence",
        ),
        (
            "$GPGGA,024637.00,3735.30670,N,12220.25810,W,1,08,1.0,12",
            "cut short: 9 of the 14 fields of a GGA sentence",
        ),
        # A time that does not parse
        ("$GPGGA,02463", "malformed timestamp: '02463'"),
    ],
)
def test_sentences_cut_short_by_their_own_fields_are_skipped(
    tmp_path, caplog, cut, reason
):
    with caplog.at_level(logging.WARNING):
        assert _read(tmp_path, *_log(1), cut) == _fixes(1)

    assert f"on line 3 ({reason}): {cut}" in caplog.text


def test_a_sentence_with_its_checksum_is_not_judged_by_its_fields(tmp_path, caplog):
    """A checksum shows where the sentence ends, however few fields it has"""
    short_gga = _sentence("GPGGA,024636.00,3735.30670,N,12220.25810,W,1,08,1.0,12.5,M")

    with caplog.at_level(logging.WARNING):
        assert _read(tmp_path, _rmc("024636.00"), short_gga) == [_fix("02:46:36")]

    assert not caplog.text


def test_a_file_that_fails_says_why(tmp_path):
    """It failed as "not a valid NMEA file", without a reason"""
    good = _rmc("024636.00")
    lines = [good[:-2] + "00", _bare(_gga("024636.00"))[:30]]

    with pytest.raises(ValueError) as excinfo:
        _read(tmp_path, *lines)

    assert str(excinfo.value) == (
        "2 of its 2 RMC and GGA sentences are malformed, the first on line 1 "
        f"(checksum does not match: 00 != {good[-2:]}): {lines[0]}"
    )


def _read_bytes(tmp_path: Path, content: bytes):
    path = tmp_path / "track.nmea"
    path.write_bytes(content)
    return [p.time for p in get_lat_lon_time_from_nmea(path)]


def test_a_sentence_with_a_byte_that_is_not_text_is_skipped(tmp_path, caplog):
    """A byte that is not UTF-8 failed the whole file"""
    damaged = _gga("024636.50").replace(",N,", ",N,\0", 1).encode("ascii")
    damaged = damaged.replace(b"\0", b"\xe9")
    with caplog.at_level(logging.WARNING):
        times = _read_bytes(
            tmp_path,
            b"\r\n".join(
                [
                    _rmc("024636.00").encode("ascii"),
                    _gga("024636.00").encode("ascii"),
                    damaged,
                    _rmc("024637.00").encode("ascii"),
                    _gga("024637.00").encode("ascii"),
                ]
            ),
        )

    assert len(times) == 2
    assert "Skipping 1 of the 5 RMC and GGA sentences" in caplog.text
    assert "on line 3 (a byte that is not text)" in caplog.text


def test_a_byte_that_is_not_text_outside_the_sentences_is_ignored(tmp_path, caplog):
    """Such as in a header line that a camera writes before the sentences"""
    with caplog.at_level(logging.WARNING):
        times = _read_bytes(
            tmp_path,
            b"@log/Z\xfcrich/\r\n"
            + _rmc("024636.00").encode("ascii")
            + b"\r\n"
            + _gga("024636.00").encode("ascii"),
        )

    assert len(times) == 1
    assert not caplog.text


@pytest.mark.parametrize(
    "head",
    [
        # the start of an MP4 video
        b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom",
        # mostly bytes that are not UTF-8
        b"\xca\xfe\xba\xbe" * 1000,
    ],
    ids=["video", "not UTF-8"],
)
def test_a_file_that_is_not_text_fails_without_being_read_whole(tmp_path, head):
    """
    A video given as an NMEA file was decoded whole, gigabytes of it: what its
    first 64 KiB show is enough
    """
    padding = b"\xff" * (64 * 1024)
    sentences = (_rmc("024636.00") + "\r\n" + _gga("024636.00") + "\r\n").encode()

    with pytest.raises(ValueError, match="^it is not text$"):
        _read_bytes(tmp_path, head + padding + sentences)


def test_a_log_longer_than_what_tells_text_is_read_whole(tmp_path):
    lines = []
    for minute in range(60):
        for second in range(10):
            time = f"02{minute:02d}0{second}.00"
            lines += [_rmc(time), _gga(time)]
    content = "".join(f"{line}\r\n" for line in lines).encode("ascii")
    assert 64 * 1024 < len(content)

    assert len(_read_bytes(tmp_path, content)) == 600


def test_bytes_that_are_not_text_and_no_fix_fail_the_file(tmp_path):
    """As a file that is not text did before"""
    with pytest.raises(ValueError):
        _read_bytes(
            tmp_path, b"\xca\xfe\r\n" + _rmc("024636.00", status="V").encode("ascii")
        )


@pytest.mark.parametrize(
    "lines",
    [
        [_rmc("024636.00")[:-2] + "00", _gga("024636.00")[:-2] + "00"],
        [_rmc("024636.00"), _gga("0246")],
    ],
)
def test_malformed_sentences_and_no_fix_fail_the_file(tmp_path, lines):
    """As a file that is not NMEA does, rather than as one without a fix"""
    with pytest.raises(ValueError):
        _read(tmp_path, *lines)


def test_gga_without_any_date_give_no_points(tmp_path, caplog):
    """They raised UnboundLocalError"""
    with caplog.at_level(logging.WARNING):
        assert _read(tmp_path, _gga("024636.00"), _gga("024637.00")) == []

    assert "Ignoring the 2 fixes" in caplog.text
    assert "no RMC sentence gives their date" in caplog.text


def test_no_fixes_give_no_points(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert (
            _read(
                tmp_path,
                _rmc("024636.00", status="V"),
                _gga("024636.00", quality=0),
            )
            == []
        )

    assert not caplog.text


def test_a_long_malformed_sentence_is_quoted_short(tmp_path, caplog):
    """A line of 20 kB of garbage gave a warning of 40 kB"""
    with caplog.at_level(logging.WARNING):
        assert _read(
            tmp_path, _rmc("024636.00"), _gga("024636.00"), "$GPGGA," + "x" * 20_000
        ) == [_fix("02:46:36")]

    [record] = caplog.records
    assert "Skipping 1 of the 3 RMC and GGA sentences" in record.getMessage()
    assert len(record.getMessage()) < 500


def test_a_file_is_read_once(tmp_path, caplog, monkeypatch):
    """Each video geotagged from it read it again, and warned about it again"""
    reads = []
    read = geotag_images_from_nmea_file._read_nmea_data
    monkeypatch.setattr(
        geotag_images_from_nmea_file,
        "_read_nmea_data",
        lambda nmea_file, data: reads.append(nmea_file) or read(nmea_file, data),
    )
    lines = [_rmc("024636.00"), _gga("024636.00"), _gga("0246")]

    with caplog.at_level(logging.WARNING):
        first = _read(tmp_path, *lines)
        second = _read(tmp_path, *lines)

    assert first == second == [_fix("02:46:36")]
    assert len(reads) == 1
    assert caplog.text.count("Skipping 1 of the 3") == 1

    # Changed, it is read again
    assert _read(tmp_path, *lines, _rmc("024637.00"), _gga("024637.00")) == [
        _fix("02:46:36"),
        _fix("02:46:37"),
    ]
    assert len(reads) == 2


def test_a_file_that_failed_to_read_fails_again(tmp_path):
    lines = [_rmc("024636.00")[:-2] + "00", _gga("024636.00")[:-2] + "00"]
    for _ in range(2):
        with pytest.raises(ValueError):
            _read(tmp_path, *lines)


def test_the_points_of_a_file_read_again_are_its_own(tmp_path):
    path = tmp_path / "track.nmea"
    path.write_bytes(f"{_rmc('024636.00')}\r\n{_gga('024636.00')}\r\n".encode())

    [point] = get_lat_lon_time_from_nmea(path)
    point.time += 3600

    [again] = get_lat_lon_time_from_nmea(path)
    assert again.time == point.time - 3600
