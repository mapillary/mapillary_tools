# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import datetime
import struct
from pathlib import Path

import pytest

from mapillary_tools import (
    exceptions,
    process_geotag_properties as pgp,
    sample_video,
    seventymai_log_parser,
    types,
)
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor
from mapillary_tools.geotag.video_extractors.native import NativeVideoExtractor

CLIP = "NO20240601-121500-000123F.MP4"
PREVIOUS_CLIP = "NO20240601-121400-000122F.MP4"
NEXT_CLIP = "NO20240601-121600-000124F.MP4"

# The start of the clip by the GPS clock
START = 1717236900


def _box(box_type: bytes, data: bytes) -> bytes:
    return struct.pack(">I", 8 + len(data)) + box_type + data


def _build_video(duration: float) -> bytes:
    """A video with no GPS of its own, as 70mai clips are, of the given duration"""
    ftyp = _box(b"ftyp", b"mp42\x00\x00\x00\x00isomavc1mp42")
    mvhd = struct.pack(">4xIIII", 0, 0, 1000, int(duration * 1000)).ljust(100, b"\x00")
    return ftyp + _box(b"moov", _box(b"mvhd", mvhd))


def _position(t: int) -> tuple[float, float]:
    # As the log writes them, to 6 decimals
    return (
        round(47.3769 + (t - START) * 0.0001, 6),
        round(8.5417 + (t - START) * 0.0002, 6),
    )


def _row(t: int, clip: str = CLIP, status: str = "A") -> str:
    lat, lon = _position(t)
    return f"{t},{status},{lat:.6f},{lon:.6f},11500,2388,-81,9,40,{clip},0,0,0"


def _rows(times, clip: str = CLIP) -> list[str]:
    return [_row(t, clip) for t in times]


def _no_fix_row(clip: str = CLIP) -> str:
    # A camera without a fix writes a placeholder time and no position
    return f"1609430400,V,0.000000,0.000000,0,0,0.00,0.00,0.00,{clip},0,0,0"


def _write(
    folder: Path,
    lines: list[str],
    name: str = "GPSData000001.txt",
    header: bool = True,
) -> None:
    # The camera writes "$V02" each time it starts logging
    folder.joinpath(name).write_text(
        "\n".join(["$V02", *lines] if header else lines) + "\n"
    )


def _clip(folder: Path, name: str = CLIP, duration: float = 60.0) -> Path:
    video_path = folder / name
    video_path.write_bytes(_build_video(duration))
    return video_path


def _extract(video_path: Path) -> list[tuple[float, float, float, float | None]]:
    points = NativeVideoExtractor(video_path).extract().points
    return [(p.time, p.lat, p.lon, p.epoch_time) for p in points]  # type: ignore


def _expected(times, start_time: float) -> list[tuple[float, float, float, float]]:
    return [(t - start_time, *_position(t), float(t)) for t in times]


# The rows of a clip recorded in the middle of a recording: a row every 1.5
# seconds, sometimes a stale fix repeated (START + 4)
CLIP_TIMES = [START + t for t in (0, 1, 3, 4, 6, 7, 9, 10, 12, 13)] + [
    START + t for t in range(15, 60, 2)
]


def test_clip_recorded_with_a_fix(tmp_path: Path):
    video_path = _clip(tmp_path)
    _write(
        tmp_path,
        [
            *_rows(range(START - 60, START, 2), PREVIOUS_CLIP),
            *_rows(CLIP_TIMES[:4]),
            _row(START + 4),
            # Not valid fixes, nor rows of the log
            _no_fix_row(),
            _row(START + 5, status="V"),
            f"{START + 5},A,0.000000,0.000000,0,0,0,0,0,{CLIP},0,0,0",
            f"{START + 5},A, 0.000000,      nan,0,0,0,0,0,{CLIP},0,0,0",
            f"-28801,A,47.377400,8.542700,0,0,0,0,0,{CLIP},0,0,0",
            f"{START + 5},A,47.377400,8.542700,0,0,0,{CLIP},0,0,0",
            f"x,A,47.377400,8.542700,0,0,0,0,0,{CLIP},0,0,0",
            *_rows(CLIP_TIMES[4:]),
            "0,V, 0.000000,      nan,-1,45,0,0,0,0,0,0,0",
            *_rows(range(START + 60, START + 120, 2), NEXT_CLIP),
        ],
    )

    # The first fix marks the start of the clip
    assert _extract(video_path) == _expected(CLIP_TIMES, START)

    metadata = NativeVideoExtractor(video_path).extract()
    assert metadata.filetype == types.FileType.VIDEO
    assert metadata.make is None and metadata.model is None


@pytest.mark.parametrize(
    "before",
    [
        [],
        # Rows that name no clip, nor are rows of the log
        ["0,V, 0.000000,      nan,-1,45,0,0,0,0,0,0,0", "1717236800,A,47.3"],
        # The camera logged another recording before
        [*_rows(range(START - 3600, START - 3540, 2), PREVIOUS_CLIP), "$V02"],
    ],
)
def test_first_fix_came_late(tmp_path: Path, before: list[str]):
    # A camera that is switched on records before it has a fix, and some
    # write no rows until then
    video_path = _clip(tmp_path)
    times = [t for t in CLIP_TIMES if START + 20 <= t]
    _write(tmp_path, [*before, *_rows(times)])

    # The last fix marks the end of the clip
    assert _extract(video_path) == _expected(times, times[-1] - 60.0)


def test_short_clip_at_the_top_of_a_log_without_header(tmp_path: Path):
    # A log without "$V02" continues one that is not there, such as one cut or
    # rotated away, so its first rows don't tell when the camera got a fix
    video_path = _clip(tmp_path)
    times = [t for t in CLIP_TIMES if START + 20 <= t]
    _write(tmp_path, _rows(times), header=False)

    assert _extract(video_path) == _expected(times, times[0])


def test_clip_ended_early(tmp_path: Path):
    # The camera stopped recording, and logging, 20 seconds into the clip.
    # Its fixes span much less than the clip, but the camera had a fix when it
    # started the clip: it logged the previous one
    video_path = _clip(tmp_path)
    times = [t for t in CLIP_TIMES if t <= START + 20]
    _write(
        tmp_path,
        [
            *_rows(range(START - 60, START, 2), PREVIOUS_CLIP),
            *_rows(times),
            "$V02",
            *_rows(range(START + 100, START + 160, 2), NEXT_CLIP),
        ],
    )

    # The first fix marks the start of the clip
    assert _extract(video_path) == _expected(times, times[0])


def test_clip_logged_across_a_restart_of_the_log(tmp_path: Path):
    # Where its rows start tells whether the camera had a fix at its start
    video_path = _clip(tmp_path)
    times = [t for t in CLIP_TIMES if t <= START + 10 or START + 30 <= t <= START + 40]
    _write(
        tmp_path,
        [
            *_rows(range(START - 60, START, 2), PREVIOUS_CLIP),
            *_rows(t for t in times if t <= START + 10),
            "$V02",
            *_rows(t for t in times if START + 30 <= t),
        ],
    )

    assert _extract(video_path) == _expected(times, times[0])


def test_short_clip_at_the_top_of_the_next_log(tmp_path: Path):
    # The next log continues the previous one, without "$V02"
    video_path = _clip(tmp_path)
    times = [t for t in CLIP_TIMES if t <= START + 20]
    _write(tmp_path, _rows(range(START - 60, START, 2), PREVIOUS_CLIP))
    _write(tmp_path, _rows(times), name="GPSData000002.txt", header=False)

    assert _extract(video_path) == _expected(times, times[0])


def test_first_fix_came_a_few_seconds_late(tmp_path: Path):
    # As late as a stall of the GPS in the middle of a recording
    video_path = _clip(tmp_path)
    times = [t for t in CLIP_TIMES if START + 6 <= t]
    _write(tmp_path, _rows(times))

    assert _extract(video_path) == _expected(times, times[0])


def test_rows_without_a_fix_before_the_first_fix(tmp_path: Path):
    # Others write rows without a fix until then
    video_path = _clip(tmp_path)
    times = [t for t in CLIP_TIMES if START + 3 <= t]
    _write(tmp_path, [_no_fix_row(), _no_fix_row(), *_rows(times)])

    assert _extract(video_path) == _expected(times, times[-1] - 60.0)


def test_rows_without_a_fix_after_the_last_fix(tmp_path: Path):
    # The camera lost its fix before the end of the clip
    video_path = _clip(tmp_path)
    times = [t for t in CLIP_TIMES if t < START + 30]
    _write(tmp_path, [*_rows(times), _no_fix_row(), _no_fix_row()])

    assert _extract(video_path) == _expected(times, times[0])


def test_rows_without_a_fix_at_both_ends(tmp_path: Path):
    video_path = _clip(tmp_path)
    _write(tmp_path, [_no_fix_row(), *_rows(CLIP_TIMES[5:-5]), _no_fix_row()])

    with pytest.raises(exceptions.MapillaryVideoGPSNotFoundError):
        NativeVideoExtractor(video_path).extract()


def test_fixes_span_a_few_seconds_more_than_the_clip(tmp_path: Path):
    video_path = _clip(tmp_path, duration=57.5)
    _write(tmp_path, _rows(CLIP_TIMES))
    assert _extract(video_path) == _expected(CLIP_TIMES, START)

    # Placed by the last fix, those that span more than the clip are left out
    _write(tmp_path, [_no_fix_row(), *_rows(CLIP_TIMES)])
    assert _extract(video_path) == _expected(CLIP_TIMES[2:], CLIP_TIMES[-1] - 57.5)


def test_fixes_span_much_more_than_the_clip(tmp_path: Path):
    video_path = _clip(tmp_path, duration=2.0)
    _write(tmp_path, _rows(CLIP_TIMES))

    with pytest.raises(exceptions.MapillaryVideoGPSNotFoundError):
        NativeVideoExtractor(video_path).extract()


def test_no_rows_of_the_clip(tmp_path: Path):
    video_path = _clip(tmp_path)
    with pytest.raises(exceptions.MapillaryVideoGPSNotFoundError):
        NativeVideoExtractor(video_path).extract()

    _write(tmp_path, [*_rows(CLIP_TIMES, PREVIOUS_CLIP), _no_fix_row()])
    with pytest.raises(exceptions.MapillaryVideoGPSNotFoundError):
        NativeVideoExtractor(video_path).extract()


@pytest.mark.parametrize(
    "logged_name",
    [
        "NO20240601-121500-000123F.MP4",
        # A camera that leaves characters of a longer name behind
        "NO20240601-121500-000123F.MP44",
        "NO20240601-121500-000123F.mp4",
        "no20240601-121500-000123f.MP4",
    ],
)
def test_clip_names(tmp_path: Path, logged_name: str):
    video_path = _clip(tmp_path, name="NO20240601-121500-000123F.mp4")
    _write(tmp_path, _rows(CLIP_TIMES, logged_name))

    assert _extract(video_path) == _expected(CLIP_TIMES, START)


def test_rows_continued_in_the_next_log(tmp_path: Path):
    video_path = _clip(tmp_path)
    _write(tmp_path, _rows(CLIP_TIMES[:10]), name="GPSData000001.txt")
    _write(tmp_path, _rows(CLIP_TIMES[10:]), name="gpsdata000002.TXT")
    # Not a log
    _write(tmp_path, _rows([START - 30]), name="notes.txt")

    assert _extract(video_path) == _expected(CLIP_TIMES, START)


def test_log_read_once_for_all_its_clips(tmp_path: Path):
    _write(
        tmp_path,
        [*_rows(CLIP_TIMES), *_rows(range(START + 60, START + 120, 2), NEXT_CLIP)],
    )
    seventymai_log_parser._index_log.cache_clear()

    assert _extract(_clip(tmp_path)) == _expected(CLIP_TIMES, START)
    assert _extract(_clip(tmp_path, name=NEXT_CLIP)) == _expected(
        range(START + 60, START + 120, 2), START + 60
    )
    assert seventymai_log_parser._index_log.cache_info().misses == 1


def test_file_types(tmp_path: Path):
    video_path = _clip(tmp_path)
    _write(tmp_path, _rows(CLIP_TIMES))

    assert NativeVideoExtractor(video_path, filetypes={types.FileType.VIDEO}).extract()
    # Not one of the native file types
    with pytest.raises(exceptions.MapillaryVideoGPSNotFoundError):
        NativeVideoExtractor(video_path, filetypes={types.FileType.CAMM}).extract()


def test_process(tmp_path: Path):
    video_path = _clip(tmp_path)
    _write(tmp_path, _rows(CLIP_TIMES))

    [metadata] = pgp.process_geotag_properties(
        tmp_path,
        None,
        geotag_source=[],
        geotag_source_path=None,
        video_geotag_source=[],
    )

    assert isinstance(metadata, types.VideoMetadata), metadata
    assert metadata.filename == video_path
    assert [(p.time, p.lat, p.lon) for p in metadata.points] == [
        (t - START, *_position(t)) for t in CLIP_TIMES
    ]


def test_sample_video_reads_the_clock(tmp_path: Path):
    video_path = _clip(tmp_path)
    _write(tmp_path, _rows(CLIP_TIMES))

    points = sample_video._read_telemetry(video_path)
    assert sample_video._gps_clock_start_time(
        points
    ) == datetime.datetime.fromtimestamp(START, tz=datetime.timezone.utc)


def test_gpx_sync(tmp_path: Path):
    video_path = _clip(tmp_path)
    _write(tmp_path, _rows(CLIP_TIMES))
    gpx_path = tmp_path / "track.gpx"
    gpx_path.write_text(
        '<gpx version="1.1" creator="test"><trk><trkseg>'
        '<trkpt lat="47.1" lon="8.1"><time>2024-06-01T10:14:50Z</time></trkpt>'
        '<trkpt lat="47.2" lon="8.2"><time>2024-06-01T10:15:00Z</time></trkpt>'
        '<trkpt lat="47.3" lon="8.3"><time>2024-06-01T10:15:10Z</time></trkpt>'
        "</trkseg></trk></gpx>"
    )
    # The GPX track is placed by the GPS clock of the log
    video_metadata = GPXVideoExtractor(video_path, gpx_path).extract()
    assert [p.time for p in video_metadata.points] == [-10.0, 0.0, 10.0]
