import io
import logging
import struct

from mapillary_tools import cam70mai_parser, telemetry
from mapillary_tools.geotag.video_extractors.native import Cam70MaiVideoExtractor
from mapillary_tools.mp4.mp4_sample_parser import RawSample


def test_extract_tracks_pairs_hint_with_video_samples(monkeypatch):
    hint_sample = _sample(offset=0, size=493, timedelta=0)
    video_sample = _sample(offset=0, size=493, timedelta=10)

    class Track:
        def __init__(self, handler, sample):
            self.trak_children = [
                {
                    "type": b"mdia",
                    "data": [
                        {"type": b"hdlr", "data": {"handler_type": handler}}
                    ],
                }
            ]
            self.sample = sample

        def extract_raw_samples(self):
            return iter([self.sample])

        def extract_tkhd_boxdata(self):
            return {"width": 1, "height": 1}

    hint_track = Track(b"hint", hint_sample)
    video_track = Track(b"vide", video_sample)

    class Movie:
        def extract_tracks(self):
            return iter([hint_track, video_track])

    monkeypatch.setattr(
        cam70mai_parser.MovieBoxParser, "parse_stream", lambda _fp: Movie()
    )
    record = _record(401_000_000, -742_000_000, 1_700_000_000, fix=b"A")

    tracks = cam70mai_parser._extract_tracks(io.BytesIO(record))

    assert tracks is not None
    assert tracks[0] is hint_track
    assert tracks[2] is video_track


def test_extract_points_uses_track_times_and_decodes_gps(monkeypatch, caplog):
    records = [
        _record(401_000_000, -742_000_000, 1_700_000_000, fix=b"A"),
        _record(401_500_000, -742_500_000, 1_700_000_000, fix=b"A"),
        _record(0, 0, 1_700_000_000, fix=b"V"),
        _record(402_000_000, -743_000_000, 1_700_000_180, fix=b"A"),
    ]
    hint_samples = [
        _sample(index * len(record), len(record), timedelta=0)
        for index, record in enumerate(records)
    ]
    video_deltas = [2, 2, 6, 2]
    video_samples = [
        _sample(
            index * len(record),
            len(record),
            timedelta=video_deltas[index],
        )
        for index, record in enumerate(records)
    ]

    class Track:
        def extract_mdhd_boxdata(self):
            return {"timescale": 10}

    hint_track = Track()
    video_track = Track()
    monkeypatch.setattr(cam70mai_parser, "_extract_tracks", lambda _fp: (
        hint_track,
        hint_samples,
        video_track,
        video_samples,
    ))
    with caplog.at_level(logging.DEBUG, logger=cam70mai_parser.LOG.name):
        points = cam70mai_parser.extract_points(io.BytesIO(b"".join(records)))

    assert points is not None
    assert [
        (p.time, p.lat, p.lon, p.alt, p.angle, p.ground_speed) for p in points
    ] == [
        (
            0.0,
            40.1,
            -74.2,
            float(records[0][0x1F]),
            float(records[0][0x17]),
            0.45,
        ),
        (
            1.0,
            40.2,
            -74.3,
            float(records[3][0x1F]),
            float(records[3][0x17]),
            0.45,
        ),
    ]
    assert [p.epoch_time for p in points] == [
        1_700_028_800.0,
        1_700_028_801.0,
    ]
    assert "2 distinct values across 4 frames" in caplog.text
    assert "2023-11-14T22:13:20Z (1700000000): present in 3 frame(s)" in caplog.text
    assert "2023-11-14T22:16:20Z (1700000180): present in 1 frame(s)" in caplog.text
    assert "Using 2023-11-15T06:13:20Z (1700028800)" in caplog.text


def test_video_extractor_uses_parsed_points(tmp_path, monkeypatch):
    video_path = tmp_path / "70mai.mp4"
    video_path.write_bytes(b"video")
    point = telemetry.GPSPoint(
        time=0.0,
        lat=40.1,
        lon=-74.2,
        alt=None,
        angle=45.0,
        epoch_time=None,
        fix=None,
        precision=None,
        ground_speed=None,
    )
    monkeypatch.setattr(cam70mai_parser, "extract_points", lambda _fp: [point])

    metadata = Cam70MaiVideoExtractor(video_path).extract()

    assert metadata.points == [point]
    assert metadata.make == "70mai"


def _record(lat: int, lon: int, timestamp: int, fix: bytes) -> bytes:
    record = bytearray(493)
    struct.pack_into("<HH", record, 0, 3, 493)
    record[0x0E] = fix[0]
    struct.pack_into("<ii", record, 0x0F, lat, lon)
    record[0x17] = 45
    record[0x1B] = 45
    record[0x1F] = 22
    struct.pack_into("<I", record, 0x15D, timestamp)
    return bytes(record)


def _sample(offset: int, size: int, timedelta: int) -> RawSample:
    return RawSample(
        description_idx=1,
        offset=offset,
        size=size,
        timedelta=timedelta,
        composition_offset=0,
        is_sync=True,
    )
