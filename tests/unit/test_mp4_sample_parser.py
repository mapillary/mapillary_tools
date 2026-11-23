# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import struct
from pathlib import Path

import pytest
from mapillary_tools.mp4 import mp4_sample_parser


def test_movie_box_parser():
    moov_parser = mp4_sample_parser.MovieBoxParser.parse_file(
        Path("tests/data/videos/sample-5s.mp4")
    )
    assert 2 == len(list(moov_parser.extract_tracks()))
    video_track = moov_parser.extract_track_at(0)
    assert video_track.is_video_track()
    aac_track = moov_parser.extract_track_at(1)
    assert not aac_track.is_video_track()
    samples = list(video_track.extract_samples())
    raw_samples = list(video_track.extract_raw_samples())
    assert 171 == len(samples)
    assert len(samples) == len(raw_samples)
    assert {
        "version": 0,
        "flags": 3,
        "creation_time": 0,
        "modification_time": 0,
        "track_ID": 1,
        "duration": 5700,
        "layer": 0,
        "alternate_group": 0,
        "volume": 0,
        # "matrix": [65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824],
        "width": 125829120,
        "height": 70778880,
    } == {
        k: v
        for k, v in video_track.extract_tkhd_boxdata().items()
        if k
        in [
            "version",
            "flags",
            "creation_time",
            "modification_time",
            "track_ID",
            "duration",
            "layer",
            "alternate_group",
            "volume",
            "width",
            "height",
        ]
    }
    assert isinstance(video_track.extract_tkhd_boxdata(), dict)
    for sample, raw_sample in zip(samples, raw_samples):
        assert sample.raw_sample.offset == raw_sample.offset
        assert sample.raw_sample.is_sync == raw_sample.is_sync
        assert sample.raw_sample.size == raw_sample.size


def test_movie_box_parser_negative_composition_offset():
    moov_parser = mp4_sample_parser.MovieBoxParser.parse_file(
        Path("tests/data/videos/sample-5s_h265.mp4")
    )
    assert 2 == len(list(moov_parser.extract_tracks()))
    video_track = moov_parser.extract_track_at(0)
    assert video_track.is_video_track()
    raw_samples = list(video_track.extract_raw_samples())
    assert 146 == len(raw_samples)
    # Make sure the parser can parse negative composition offsets
    assert 0 < len([s for s in raw_samples if s.composition_offset < 0])


def _box(box_type: bytes, data: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(data), box_type) + data


def _full_box(box_type: bytes, data: bytes) -> bytes:
    # version 0 and no flags
    return _box(box_type, b"\x00\x00\x00\x00" + data)


def _table(box_type: bytes, fmt: str, entries: list) -> bytes:
    flat = [
        v
        for entry in entries
        for v in (entry if isinstance(entry, tuple) else (entry,))
    ]
    return _full_box(box_type, struct.pack(f">I{len(flat)}{fmt}", len(entries), *flat))


_STSD = _full_box(
    b"stsd",
    struct.pack(">I", 1)
    + struct.pack(">I4s6xH", 16 + 4, b"camm", 1)
    + b"\x00\x00\x00\x00",
)
_STSZ = _full_box(b"stsz", struct.pack(">II3I", 0, 3, 10, 20, 30))
_STCO = _table(b"stco", "I", [100, 200])
_STSC = _table(b"stsc", "I", [(1, 2, 1), (2, 1, 1)])
_STTS = _table(b"stts", "I", [(2, 1000), (1, 500)])


@pytest.mark.parametrize(
    "path",
    [
        "tests/data/videos/sample-5s.mp4",
        "tests/data/videos/sample-5s_h265.mp4",
        "tests/data/gopro_data/hero8.mp4",
        "tests/data/gopro_data/max-360mode.mp4",
    ],
)
def test_parse_sample_tables_of_videos(path):
    moov_parser = mp4_sample_parser.MovieBoxParser.parse_file(Path(path))
    for track in moov_parser.extract_tracks():
        stbl = track.stbl_data
        tables = mp4_sample_parser._parse_sample_tables(stbl)
        assert tables == mp4_sample_parser._parse_sample_tables_with_construct(stbl)
        assert tables.sizes


@pytest.mark.parametrize(
    "stbl",
    [
        _STSD + _STSZ + _STCO + _STSC + _STTS,
        # same sample size, 64-bit chunk offsets, sync samples, and boxes
        # that are not read
        _STSD
        + _full_box(b"stsz", struct.pack(">II", 7, 3))
        + _table(b"co64", "Q", [2**40, 2**40 + 14])
        + _STSC
        + _STTS
        + _table(b"stss", "I", [1, 3])
        + _box(b"sdtp", b"\x00\x00\x00\x00\x10\x20\x30"),
        # negative composition offsets
        _STSD
        + _STSZ
        + _STCO
        + _STSC
        + _STTS
        + _full_box(b"ctts", struct.pack(">I2I2I", 2, 2, 2**32 - 500, 1, 1000)),
        # the later of two chunk offset boxes
        _STSD + _STSZ + _STCO + _table(b"co64", "Q", [300, 400]) + _STSC + _STTS,
        # fewer time deltas than samples
        _STSD + _STSZ + _STCO + _STSC + _table(b"stts", "I", [(1, 1000)]),
        # empty
        b"",
        _STSD + _full_box(b"stsz", struct.pack(">II", 0, 0)),
    ],
)
def test_parse_sample_tables(stbl):
    tables = mp4_sample_parser._parse_sample_tables(stbl)
    assert tables == mp4_sample_parser._parse_sample_tables_with_construct(stbl)


@pytest.mark.parametrize(
    "stbl",
    [
        # a table with more entries than the box holds
        _STSD + _full_box(b"stsz", struct.pack(">II2I", 0, 3, 10, 20)) + _STCO,
        _STSD + _STSZ + _full_box(b"stco", struct.pack(">II", 2, 100)) + _STSC,
        _STSD + _STSZ + _STCO + _full_box(b"stts", struct.pack(">I", 1)),
        # a box without its version and flags
        _STSD + _box(b"stsz", b"") + _STCO,
        # a box cut short, or a box header cut short
        (_STSD + _STSZ + _STCO + _STSC)[:-3],
        _STSD + _STSZ + b"\x00\x00\x00",
        # a box with a 64-bit size
        _STSD + struct.pack(">I4sQ", 1, b"stsz", 16 + len(_STSZ) - 8) + _STSZ[8:],
        # a box with a size too small, and a size of 0 (to the end)
        _STSD + struct.pack(">I4s", 4, b"free") + _STSZ,
        _STSD + _STSZ + struct.pack(">I4s", 0, b"free") + b"\x00" * 8,
        _STSD
        + _STSZ
        + _STCO
        + _STSC
        + _STTS
        + struct.pack(">I4s", 0, b"free")
        + b"\x00" * 8,
        # sample descriptions that construct can not read
        _box(b"stsd", b"\x00\x00\x00\x00\x00\x00\x00\x05") + _STSZ,
    ],
)
def test_parse_irregular_sample_tables(stbl, monkeypatch):
    with pytest.raises(mp4_sample_parser._IrregularBoxError):
        mp4_sample_parser._parse_sample_tables(stbl)

    def extract(stbl: bytes) -> tuple[list[dict], list]:
        descriptions, raw_samples = (
            mp4_sample_parser.extract_raw_samples_from_stbl_data(stbl)
        )
        return descriptions, list(raw_samples)

    # Left to construct, which drops the box that it fails to read and the
    # boxes after it: the samples are those that construct alone reads
    samples = extract(stbl)

    def irregular(stbl: bytes):
        raise mp4_sample_parser._IrregularBoxError()

    monkeypatch.setattr(mp4_sample_parser, "_parse_sample_tables", irregular)
    assert samples == extract(stbl)
