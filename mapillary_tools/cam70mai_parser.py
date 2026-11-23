"""
Extract GPS from the "hint" blocks written by 70mai Dashcams.
Based on investigation this data is written only in Front Camera videos.

The decoded positions and GPS times match GPSData000001.txt.
Data stored in the "hint" is written per frame, meaning that 1 second of video will have 30 records.
The record timestamp is a Unix timestamp, but some initial records may contain
a different value. The most common record timestamp, plus TIMEZONE_OFFSET, anchors
the first GPS point; later timestamps are offset by their video-relative time.

"""
from __future__ import annotations

import datetime
import dataclasses
import io
import logging
import math
import struct
import typing as T

from . import telemetry
from .mp4 import construct_mp4_parser as mp4parser
from .mp4 import simple_mp4_parser as sparser
from .mp4.mp4_sample_parser import MovieBoxParser, RawSample, TrackBoxParser

LOG = logging.getLogger(__name__)

_RECORD_SIZE = 493
_PREFIX_VALUE = 3
_COORDINATE_SCALE = 10_000_000
_CENTIMETERS_PER_METER = 100
_RECORD_TIMESTAMP_OFFSET = 0x15D
TIMEZONE_OFFSET = datetime.timedelta(hours=8)


class _UnsupportedRecordError(Exception):
    pass


def extract_points(fp: T.BinaryIO) -> list[telemetry.GPSPoint] | None:
    tracks = _extract_tracks(fp)
    if tracks is None:
        return None

    _, hint_samples, video_track, video_samples = tracks
    if len(hint_samples) != len(video_samples):
        return None

    timescale = video_track.extract_mdhd_boxdata()["timescale"]
    if not timescale or not video_samples:
        return None

    video_times: list[float] = []
    elapsed_ticks = 0
    for sample in video_samples:
        video_times.append(
            (elapsed_ticks + sample.composition_offset) / timescale
        )
        elapsed_ticks += sample.timedelta
    first_video_time = min(video_times)

    points_by_second: dict[int, telemetry.GPSPoint] = {}
    timestamp_counts: dict[int, int] = {}

    for sample_index, (sample, video_time) in enumerate(
        zip(hint_samples, video_times)
    ):
        if sample.size != _RECORD_SIZE:
            return None

        fp.seek(sample.offset, io.SEEK_SET)
        record = fp.read(sample.size)
        if len(record) != sample.size:
            raise EOFError(
                f"Truncated 70mai track sample {sample_index}: "
                f"expected {sample.size} bytes, got {len(record)}"
            )

        (timestamp,) = struct.unpack_from("<I", record, _RECORD_TIMESTAMP_OFFSET)
        timestamp_counts[timestamp] = timestamp_counts.get(timestamp, 0) + 1

        try:
            point = _parse_record(record, video_time - first_video_time)
        except _UnsupportedRecordError:
            return None

        if point is not None:
            second = math.floor(point.time)
            previous = points_by_second.get(second)
            if previous is None or point.time < previous.time:
                points_by_second[second] = point

    most_common_timestamp = _log_timestamp_counts(timestamp_counts)
    if most_common_timestamp is None or not points_by_second:
        return None

    points = [points_by_second[second] for second in sorted(points_by_second)]
    first_point_time = points[0].time
    first_epoch_time = (
        most_common_timestamp + TIMEZONE_OFFSET.total_seconds()
    )
    LOG.debug(
        "Using %s (%d) as the first GPS point timestamp after offset %s",
        _format_timestamp(first_epoch_time),
        first_epoch_time,
        TIMEZONE_OFFSET,
    )
    return [
        dataclasses.replace(
            point,
            epoch_time=first_epoch_time + point.time - first_point_time,
        )
        for point in points
    ]


def _format_timestamp(timestamp: float) -> str:
    return (
        datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _log_timestamp_counts(timestamp_counts: dict[int, int]) -> int | None:
    if not timestamp_counts:
        return None

    LOG.debug(
        "70mai record timestamps: %d distinct values across %d frames",
        len(timestamp_counts),
        sum(timestamp_counts.values()),
    )
    for timestamp, frame_count in sorted(timestamp_counts.items()):
        LOG.debug(
            "  %s (%d): present in %d frame(s)",
            _format_timestamp(timestamp),
            timestamp,
            frame_count,
        )

    return max(timestamp_counts, key=timestamp_counts.get)


def _parse_record(record: bytes, time: float) -> telemetry.GPSPoint | None:
    if len(record) != _RECORD_SIZE:
        raise _UnsupportedRecordError("Unexpected 70mai record size")

    prefix, declared_size = struct.unpack_from("<HH", record)
    if prefix != _PREFIX_VALUE or declared_size != _RECORD_SIZE:
        raise _UnsupportedRecordError("Unexpected 70mai record header")

    # Records without a GPS fix are valid but do not produce a point.
    if record[0x0E] != ord("A"):
        return None

    lat_raw, lon_raw = struct.unpack_from("<ii", record, 0x0F)
    lat = lat_raw / _COORDINATE_SCALE
    lon = lon_raw / _COORDINATE_SCALE
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise _UnsupportedRecordError("Invalid 70mai coordinates")

    return telemetry.GPSPoint(
        time=time,
        lat=lat,
        lon=lon,
        # The template identifies this byte as altitude, likely in meters.
        alt=float(record[0x1F]),
        angle=float(record[0x17]),
        epoch_time=None,
        fix=None,
        precision=None,
        ground_speed=record[0x1B] / _CENTIMETERS_PER_METER,
    )


def _extract_tracks(
    fp: T.BinaryIO,
) -> tuple[TrackBoxParser, list[RawSample], TrackBoxParser, list[RawSample]] | None:
    fp.seek(0)
    try:
        movie = MovieBoxParser.parse_stream(fp)
    except sparser.ParsingError:
        return None

    hint_tracks: list[tuple[TrackBoxParser, list[RawSample]]] = []
    video_tracks: list[tuple[TrackBoxParser, list[RawSample]]] = []
    for track in movie.extract_tracks():
        hdlr = mp4parser.find_box_at_path(
            track.trak_children, [b"mdia", b"hdlr"]
        )
        if hdlr is None:
            continue

        handler = hdlr["data"]["handler_type"]
        if handler == b"hint":
            samples = list(track.extract_raw_samples())
            if samples and all(sample.size == _RECORD_SIZE for sample in samples):
                first_sample = samples[0]
                fp.seek(first_sample.offset, io.SEEK_SET)
                header = fp.read(4)
                if len(header) == 4 and struct.unpack("<HH", header) == (
                    _PREFIX_VALUE,
                    _RECORD_SIZE,
                ):
                    hint_tracks.append((track, samples))
        elif handler == b"vide":
            video_tracks.append((track, list(track.extract_raw_samples())))

    for hint_track, hint_samples in hint_tracks:
        matching_video_tracks = [
            (track, samples)
            for track, samples in video_tracks
            if len(samples) == len(hint_samples)
        ]
        if not matching_video_tracks:
            continue

        video_track, video_samples = max(
            matching_video_tracks,
            key=lambda item: (
                item[0].extract_tkhd_boxdata()["width"]
                * item[0].extract_tkhd_boxdata()["height"]
            ),
        )
        return hint_track, hint_samples, video_track, video_samples

    return None
