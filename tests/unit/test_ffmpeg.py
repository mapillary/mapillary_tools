# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import subprocess
from pathlib import Path

import py.path
import pytest
from mapillary_tools import ffmpeg

from ..integration.fixtures import pytest_skip_if_not_ffmpeg_installed, setup_data


def test_ffmpeg_run_ok():
    pytest_skip_if_not_ffmpeg_installed()

    ff = ffmpeg.FFMPEG()
    ff.run_ffmpeg_non_interactive(["-version"])


@pytest.mark.xfail(
    reason="ffmpeg run_ffmpeg_non_interactive should raise FFmpegCalledProcessError",
    raises=ffmpeg.FFmpegCalledProcessError,
)
def test_ffmpeg_run_raise():
    pytest_skip_if_not_ffmpeg_installed()

    ff = ffmpeg.FFMPEG()
    ff.run_ffmpeg_non_interactive(["foo"])


def test_ffmpeg_extract_frames_ok(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    ff = ffmpeg.FFMPEG()

    video_path = Path(setup_data.join("videos/sample-5s.mp4"))

    sample_dir = Path(setup_data.join("videos/samples"))
    sample_dir.mkdir()

    ff.extract_frames_by_interval(video_path, sample_dir, sample_interval=1)

    results = list(ff.sort_selected_samples(sample_dir, video_path))
    assert len(results) == 6
    for idx, (file_idx, frame_paths) in enumerate(results):
        assert idx + 1 == file_idx
        assert 1 == len(frame_paths)
        assert frame_paths[0] is not None
        assert frame_paths[0].exists()

    results = list(ff.sort_selected_samples(sample_dir, video_path, ["0"]))
    assert len(results) == 6
    for idx, (file_idx, frame_paths) in enumerate(results):
        assert idx + 1 == file_idx
        assert 1 == len(frame_paths)
        assert frame_paths[0] is None


def test_ffmpeg_extract_frames_with_specifier_ok(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    ff = ffmpeg.FFMPEG()

    video_path = Path(setup_data.join("videos/sample-5s.mp4"))

    sample_dir = Path(setup_data.join("videos/samples"))
    sample_dir.mkdir()

    ff.extract_frames_by_interval(
        video_path,
        sample_dir,
        sample_interval=1,
        stream_specifier=0,
    )

    results = list(ff.sort_selected_samples(sample_dir, video_path, [0]))
    assert len(results) == 6
    for idx, (file_idx, frame_paths) in enumerate(results):
        assert idx + 1 == file_idx
        assert 1 == len(frame_paths)
        assert frame_paths[0] is not None
        assert frame_paths[0].exists()

    results = list(ff.sort_selected_samples(sample_dir, video_path, [1]))
    assert len(results) == 6
    for idx, (file_idx, frame_paths) in enumerate(results):
        assert idx + 1 == file_idx
        assert 1 == len(frame_paths)
        assert frame_paths[0] is None


def test_ffmpeg_extract_specified_frames_ok(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    ff = ffmpeg.FFMPEG()

    video_path = Path(setup_data.join("videos/sample-5s.mp4"))

    sample_dir = Path(setup_data.join("videos/samples"))
    sample_dir.mkdir()

    ff.extract_specified_frames(video_path, sample_dir, frame_indices={2, 9})

    results = list(ff.sort_selected_samples(sample_dir, video_path))
    assert len(results) == 2

    for idx, (file_idx, frame_paths) in enumerate(results):
        assert idx + 1 == file_idx
        assert frame_paths[0] is not None
        assert frame_paths[0].exists()


def test_ffmpeg_extract_specified_frames_empty_ok(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    ff = ffmpeg.FFMPEG()

    video_path = Path(setup_data.join("videos/sample-5s.mp4"))

    sample_dir = Path(setup_data.join("videos/samples"))
    sample_dir.mkdir()

    ff.extract_specified_frames(video_path, sample_dir, frame_indices=set())

    results = list(ff.sort_selected_samples(sample_dir, video_path))
    assert len(results) == 0


def test_ffmpeg_extract_specified_frames_source_names(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    ff = ffmpeg.FFMPEG()

    video_path = Path(setup_data.join("videos/sample-5s.mp4"))

    sample_dir = Path(setup_data.join("videos/samples_source_names"))
    sample_dir.mkdir()

    ff.extract_specified_frames(
        video_path, sample_dir, frame_indices={2, 9}, source_frame_names=True
    )

    results = list(ff.sort_selected_samples(sample_dir, video_path))
    assert [file_idx for file_idx, _ in results] == [2, 9]
    for file_idx, frame_paths in results:
        assert frame_paths[0] is not None
        assert frame_paths[0].name.endswith(f"_{file_idx:06d}.jpg")


def test_rename_extracted_to_source_indices(tmp_path: Path):
    video_stem = "GX040129"
    prefix = tmp_path / video_stem
    spec = 0
    sequential = [1, 2, 3]
    source_frames = [0, 14, 33717]
    for n in sequential:
        (tmp_path / f"{video_stem}_{spec}_{n:06d}.jpg").write_bytes(b"x" * n)

    ffmpeg.FFMPEG._rename_extracted_to_source_indices(prefix, spec, source_frames)

    names = sorted(p.name for p in tmp_path.glob("*.jpg"))
    assert names == [
        f"{video_stem}_{spec}_{idx:06d}.jpg" for idx in source_frames
    ]
    assert (tmp_path / f"{video_stem}_{spec}_{14:06d}.jpg").read_bytes() == b"xx"


def test_rename_extracted_to_source_indices_collision(tmp_path: Path):
    video_stem = "clip"
    prefix = tmp_path / video_stem
    spec = "v"
    (tmp_path / f"{video_stem}_{spec}_000001.jpg").write_bytes(b"a")
    (tmp_path / f"{video_stem}_{spec}_000002.jpg").write_bytes(b"b")

    ffmpeg.FFMPEG._rename_extracted_to_source_indices(prefix, spec, [2, 9])

    assert (tmp_path / f"{video_stem}_{spec}_000002.jpg").read_bytes() == b"a"
    assert (tmp_path / f"{video_stem}_{spec}_000009.jpg").read_bytes() == b"b"
    assert not (tmp_path / f"{video_stem}_{spec}_000001.jpg").exists()


def test_probe_format_and_streams_ok(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    video_path = Path(setup_data.join("videos/sample-5s.mp4"))

    ff = ffmpeg.FFMPEG()
    probe_output = ff.probe_format_and_streams(video_path)
    probe = ffmpeg.Probe(probe_output)

    start_time = probe.probe_video_start_time()
    assert start_time is None
    max_stream = probe.probe_video_with_max_resolution()
    assert max_stream is not None
    assert max_stream["index"] == 0
    assert max_stream["codec_type"] == "video"


def test_probe_format_and_streams_gopro_ok(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    video_path = Path(setup_data.join("gopro_data/hero8.mp4"))

    ff = ffmpeg.FFMPEG()
    probe_output = ff.probe_format_and_streams(video_path)
    probe = ffmpeg.Probe(probe_output)

    start_time = probe.probe_video_start_time()
    assert start_time is not None
    assert datetime.datetime.isoformat(start_time) == "2019-11-18T15:41:12.354033+00:00"
    max_stream = probe.probe_video_with_max_resolution()
    assert max_stream is not None
    assert max_stream["index"] == 0
    assert max_stream["codec_type"] == "video"


def test_ffmpeg_not_exists():
    pytest_skip_if_not_ffmpeg_installed()

    ff = ffmpeg.FFMPEG()
    try:
        ff.extract_frames_by_interval(
            Path("not_exist_a"), Path("not_exist_b"), sample_interval=2
        )
    except ffmpeg.FFmpegCalledProcessError as ex:
        assert "STDERR:" not in str(ex)
    else:
        assert False, "FFmpegCalledProcessError not raised"

    ff = ffmpeg.FFMPEG(stderr=subprocess.PIPE)
    try:
        ff.extract_frames_by_interval(
            Path("not_exist_a"), Path("not_exist_b"), sample_interval=2
        )
    except ffmpeg.FFmpegCalledProcessError as ex:
        assert "STDERR:" in str(ex)
    else:
        assert False, "FFmpegCalledProcessError not raised"


def test_ffprobe_not_exists():
    pytest_skip_if_not_ffmpeg_installed()

    ff = ffmpeg.FFMPEG()
    try:
        x = ff.probe_format_and_streams(Path("not_exist_a"))
    except ffmpeg.FFmpegCalledProcessError as ex:
        # exc from linux
        assert "STDERR:" not in str(ex)
    except RuntimeError as ex:
        # exc from macos
        assert "Empty JSON ffprobe output with STDERR: None" == str(ex)
    else:
        assert False, "RuntimeError not raised"

    ff = ffmpeg.FFMPEG(stderr=subprocess.PIPE)
    try:
        x = ff.probe_format_and_streams(Path("not_exist_a"))
    except ffmpeg.FFmpegCalledProcessError as ex:
        # exc from linux
        assert "STDERR:" in str(ex)
    except RuntimeError as ex:
        # exc from macos
        assert (
            "Empty JSON ffprobe output with STDERR: b'not_exist_a: No such file or directory"
            in str(ex)
        )
    else:
        assert False, "RuntimeError not raised"


def test_probe():
    def test_creation_time(expected, probe_creation_time, probe_duration):
        probe = ffmpeg.Probe(
            {
                "streams": [
                    {
                        "index": 0,
                        "codec_type": "video",
                        "codec_tag_string": "avc1",
                        "width": 2880,
                        "height": 1620,
                        "coded_width": 2880,
                        "coded_height": 1620,
                        "duration": probe_duration,
                        "tags": {
                            "creation_time": probe_creation_time,
                            "language": "und",
                            "handler_name": "Core Media Video",
                            "vendor_id": "[0][0][0][0]",
                            "encoder": "H.264",
                        },
                    }
                ]
            }
        )
        creation_time = probe.probe_video_start_time()
        assert expected == creation_time

    test_creation_time(
        datetime.datetime(2023, 3, 7, 1, 35, 29, 190123, tzinfo=datetime.timezone.utc),
        "2023-03-07T01:35:34.123456Z",
        "4.933333",
    )
    test_creation_time(
        datetime.datetime(2023, 3, 7, 1, 35, 29, 66667, tzinfo=datetime.timezone.utc),
        "2023-03-07T01:35:34.000000Z",
        "4.933333",
    )
    test_creation_time(
        datetime.datetime(2023, 3, 7, 1, 35, 29, 66667),
        "2023-03-07 01:35:34",
        "4.933333",
    )


def _ffmpeg_with_version(version):
    ff = ffmpeg.FFMPEG()
    ff._version_probed = True
    ff._version = version
    return ff


def test_parse_ffmpeg_version():
    """Distro and build suffixes must not defeat the version match."""
    parse = ffmpeg._FFMPEG_VERSION_RE.match

    for line, expected in [
        ("ffmpeg version 9.0.1 Copyright (c) 2000-2026", (9, 0)),
        ("ffmpeg version 8.1.2 Copyright (c) 2000-2026", (8, 1)),
        ("ffmpeg version n7.1.5 Copyright (c) 2000-2025", (7, 1)),
        ("ffmpeg version 7.0.2-static https://johnvansickle.com/ffmpeg/", (7, 0)),
        ("ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023", (6, 1)),
    ]:
        matched = parse(line)
        assert matched is not None, line
        assert (int(matched.group(1)), int(matched.group(2))) == expected, line

    # Git and nightly builds do not report a release version
    assert parse("ffmpeg version N-121246-gd52c8dbc9d Copyright (c) 2000-2026") is None


def test_ffmpeg_version_is_probed_once():
    pytest_skip_if_not_ffmpeg_installed()

    ff = ffmpeg.FFMPEG()
    assert ff.get_version() == ff.get_version()
    assert ff._version_probed

    # An unreadable binary must not be mistaken for an old one
    with pytest.raises(ffmpeg.FFmpegNotFoundError):
        ffmpeg.FFMPEG(ffmpeg_path="not_exist_ffmpeg_binary").get_version()


def test_option_spelling_by_ffmpeg_version():
    """ffmpeg 9.0 dropped -filter_script, ffmpeg < 7.1 never had -/filter."""
    legacy_filter = ["-filter_script:v", "/tmp/f.txt"]
    modern_filter = ["-/filter:v", "/tmp/f.txt"]

    for version, expected in [
        ((6, 1), legacy_filter),
        ((7, 0), legacy_filter),
        ((7, 1), modern_filter),
        ((9, 0), modern_filter),
        # Unversioned git builds track master, so assume the modern spelling
        (None, modern_filter),
    ]:
        ff = _ffmpeg_with_version(version)
        assert ff._read_filter_from_file_args("/tmp/f.txt") == expected, version

    for version, expected in [
        ((5, 0), ["-vsync", "0"]),
        ((5, 1), ["-fps_mode", "passthrough"]),
        ((9, 0), ["-fps_mode", "passthrough"]),
        (None, ["-fps_mode", "passthrough"]),
    ]:
        ff = _ffmpeg_with_version(version)
        assert ff._passthrough_fps_args() == expected, version


def test_ffmpeg_extract_specified_frames_legacy_options_ok(setup_data: py.path.local):
    """The pre-7.1 spelling must still extract the same frames.

    ffmpeg 7.1 through 8.x accept both spellings, so on those binaries this
    pins the legacy branch; elsewhere it is skipped.
    """
    pytest_skip_if_not_ffmpeg_installed()

    if not (7, 1) <= (ffmpeg.FFMPEG().get_version() or (0, 0)) < (9, 0):
        pytest.skip("ffmpeg does not accept both the legacy and modern spellings")

    video_path = Path(setup_data.join("videos/sample-5s.mp4"))
    digests = []

    for version in [(7, 0), (7, 1)]:
        sample_dir = Path(setup_data.join(f"videos/samples_{version[0]}_{version[1]}"))
        sample_dir.mkdir()

        ff = _ffmpeg_with_version(version)
        ff.extract_specified_frames(video_path, sample_dir, frame_indices={2, 9})

        results = list(ff.sort_selected_samples(sample_dir, video_path))
        assert len(results) == 2, version
        digests.append(
            [p.read_bytes() for _, paths in results for p in paths if p is not None]
        )

    # Both spellings must select the same frames byte for byte
    assert digests[0] == digests[1]
