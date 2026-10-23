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
