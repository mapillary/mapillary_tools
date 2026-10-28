# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import io
import logging
import multiprocessing
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import py.path
import pytest
from mapillary_tools import utils


def test_filter():
    images = [
        Path("foo/bar/hello.mp4/hello_123.jpg"),
        Path("/hello.mp4/hello_123.jpg"),
        Path("foo/bar/hello/hello_123.jpg"),
        Path("/hello.mp4/hell_123.jpg"),
    ]
    r = list(utils.filter_video_samples(images, Path("hello.mp4")))
    assert r == [
        Path("foo/bar/hello.mp4/hello_123.jpg"),
        Path("/hello.mp4/hello_123.jpg"),
    ]


def test_find_all_image_samples():
    image_samples_by_video_path = utils.find_all_image_samples(
        [
            # hello.mp4
            Path("foo/hello.mp4/hello_123.jpg"),
            Path("foo/hello.mp4/hello_.jpg"),
            # world.mp4
            Path("world.mp4/world_123.jpg"),
            # NOT image samples
            Path("world.mp4/hello_123.jpg"),
            Path("world.mp4/world.mp4_123.jpg"),
            Path("hello/hello_123.jpg"),
        ],
        [
            Path("foo/hello.mp4"),
            Path("hello.mp4"),
            Path("foo/world.mp4"),
            Path("world.mp4"),
            Path("."),
        ],
    )
    # Of the videos of the same name, the samples are of the one whose path,
    # relative to the folder that holds them all, their folder ends with
    assert {
        Path("foo/hello.mp4"): [
            Path("foo/hello.mp4/hello_123.jpg"),
            Path("foo/hello.mp4/hello_.jpg"),
        ],
        Path("world.mp4"): [Path("world.mp4/world_123.jpg")],
    } == image_samples_by_video_path


def test_find_image_samples_where_resolve_leaves_paths_relative(monkeypatch):
    """
    Path.resolve() leaves a path that does not exist relative on Windows with
    Python 3.9 and 3.10, which took the samples of world.mp4 for those of
    foo/world.mp4
    """
    resolve = Path.resolve
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda self, strict=False: resolve(self) if self.exists() else self,
    )
    samples, ambiguous = utils.find_image_samples(
        [Path("foo/world.mp4/world_123.jpg"), Path("world.mp4/world_123.jpg")],
        # "." exists, so it alone was made absolute
        [Path("foo/world.mp4"), Path("world.mp4"), Path(".")],
    )
    assert {
        Path("foo/world.mp4"): [Path("foo/world.mp4/world_123.jpg")],
        Path("world.mp4"): [Path("world.mp4/world_123.jpg")],
    } == samples
    assert {} == ambiguous


def test_find_image_samples_of_a_symlinked_video(tmp_path: Path):
    """
    sample_video() names the folder of a symlinked video after the link, which
    a video path resolved to the file it links to did not match
    """
    target = tmp_path / "elsewhere" / "video.mp4"
    target.parent.mkdir()
    target.write_bytes(b"")
    link = tmp_path / "videos" / "link.mp4"
    link.parent.mkdir()
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as ex:
        pytest.skip(f"Cannot create symbolic links here: {ex}")
    sample = tmp_path / "out" / "link.mp4" / "link_0_000001.jpg"

    samples, ambiguous = utils.find_image_samples([sample], [link])
    assert {link: [sample]} == samples
    assert {} == ambiguous


def test_find_image_samples_of_videos_on_different_drives(monkeypatch):
    """Videos of the same name that no path tells apart could be any of them"""

    def commonpath(paths):
        raise ValueError("Paths don't have the same drive")

    monkeypatch.setattr(utils.os.path, "commonpath", commonpath)
    samples, ambiguous = utils.find_image_samples(
        [Path("world.mp4/world_123.jpg")],
        [Path("foo/world.mp4"), Path("world.mp4")],
    )
    assert {} == samples
    assert {
        Path("world.mp4/world_123.jpg"): [Path("foo/world.mp4"), Path("world.mp4")]
    } == ambiguous


def test_find_image_samples_of_videos_of_the_same_name():
    """
    The samples of videos of the same name in different folders were all taken
    for the samples of one of them
    """
    videos = [
        Path("videos/clip.mp4"),
        Path("videos/x/clip.mp4"),
        Path("videos/y/clip.mp4"),
        Path("videos/y/z/clip.mp4"),
    ]
    # Where sample_video samples them, from videos/
    images = [
        Path("out/clip.mp4/clip_0_000001.jpg"),
        Path("out/x/clip.mp4/clip_0_000001.jpg"),
        Path("out/x/clip.mp4/clip_0_000002.jpg"),
        Path("out/y/clip.mp4/clip_0_000001.jpg"),
        Path("out/y/z/clip.mp4/clip_0_000001.jpg"),
    ]

    samples_by_video, ambiguous = utils.find_image_samples(images, videos)

    assert samples_by_video == {
        Path("videos/clip.mp4"): [Path("out/clip.mp4/clip_0_000001.jpg")],
        Path("videos/x/clip.mp4"): [
            Path("out/x/clip.mp4/clip_0_000001.jpg"),
            Path("out/x/clip.mp4/clip_0_000002.jpg"),
        ],
        Path("videos/y/clip.mp4"): [Path("out/y/clip.mp4/clip_0_000001.jpg")],
        Path("videos/y/z/clip.mp4"): [Path("out/y/z/clip.mp4/clip_0_000001.jpg")],
    }
    assert ambiguous == {}


def test_find_image_samples_that_could_be_of_several_videos():
    videos = [Path("videos/x/clip.mp4"), Path("videos/y/clip.mp4")]
    # Not where sample_video samples either of them, from videos/
    images = [
        Path("out/clip.mp4/clip_0_000001.jpg"),
        Path("out/w/clip.mp4/clip_0_000001.jpg"),
    ]

    samples_by_video, ambiguous = utils.find_image_samples(images, videos)

    assert samples_by_video == {}
    assert ambiguous == {image: videos for image in images}

    # With one video of the name, its samples are found wherever they are, as
    # before
    samples_by_video, ambiguous = utils.find_image_samples(images, videos[:1])
    assert samples_by_video == {videos[0]: images}
    assert ambiguous == {}


def test_deduplicates():
    pwd = Path(".").resolve()
    # TODO: life too short to test for windows
    if not sys.platform.startswith("win"):
        x = utils.deduplicate_paths(
            [
                Path("./foo/hello.jpg"),
                Path("./foo/bar/../hello.jpg"),
                Path(f"{pwd}/foo/bar/../hello.jpg"),
            ]
        )
        assert [Path("./foo/hello.jpg")] == list(x)


def test_filter_all(tmpdir: py.path.local):
    tmpdir.mkdir("foo")
    tmpdir.join("foo").join("hello.jpg").open("wb").close()
    tmpdir.join("foo").join("hello.jpe").open("wb").close()
    tmpdir.join("foo").join("world.TIFF").open("wb").close()
    tmpdir.join("foo").join("world.ZIP").open("wb").close()
    tmpdir.join("foo").join("world.mp4").open("wb").close()
    tmpdir.join("foo").join("world.MP4").open("wb").close()
    tmpdir.join("foo").join("world.ts").open("wb").close()
    tmpdir.join("foo").join(".jpg").open("wb").close()
    tmpdir.join("foo").join(".png").open("wb").close()
    tmpdir.join("foo").join(".zip").open("wb").close()
    tmpdir.join("foo").join(".MP4").open("wb").close()
    tmpdir.join("foo").mkdir(".git")
    # TODO: life too short to test for windows
    if not sys.platform.startswith("win"):
        assert {"foo/world.TIFF", "foo/hello.jpg", "foo/hello.jpe"} == set(
            str(p.relative_to(tmpdir))
            for p in utils.find_images(
                [
                    Path(tmpdir),
                    Path(tmpdir.join("foo").join("world.TIFF")),
                    Path(tmpdir.join("foo").join(".foo")),
                    Path(tmpdir.join("foo").join("../foo")),
                ]
            )
        )
        assert {"foo/world.zip", "foo/world.ZIP"} == set(
            str(p.relative_to(tmpdir))
            for p in utils.find_zipfiles(
                [
                    Path(tmpdir),
                    Path(tmpdir.join("foo").join("world.zip")),
                    Path(tmpdir.join("foo").join(".foo")),
                    Path(tmpdir.join("foo").join("../foo")),
                ]
            )
        )
        actual = set(
            str(p.relative_to(tmpdir))
            for p in utils.find_videos(
                [
                    Path(tmpdir),
                    Path(tmpdir.join("foo").join("world.mp4")),
                    Path(tmpdir.join("foo").join("world.ts")),
                    Path(tmpdir.join("foo").join(".foo")),
                    Path(tmpdir.join("foo").join("../foo")),
                ]
            )
        )
        # some platform filenames are case sensitive?
        assert (
            {"foo/world.MP4", "foo/world.ts"} == actual
            or {"foo/world.mp4", "foo/world.MP4", "foo/world.ts"} == actual
            or {"foo/world.mp4", "foo/world.ts"} == actual
        )


class TestConfigureLogger:
    def test_adds_one_handler(self):
        logger = logging.getLogger("mapillary_tools_test_configure_logger")
        try:
            utils.configure_logger(logger, level=logging.WARNING)
            utils.configure_logger(logger, level=logging.DEBUG)

            assert len(logger.handlers) == 1
            assert logger.level == logging.DEBUG
        finally:
            logger.handlers.clear()

    @pytest.mark.skipif(
        "fork" not in multiprocessing.get_all_start_methods(),
        reason="fork is not available",
    )
    def test_forked_worker_logs_once(self, tmp_path: Path):
        """A forked worker inherits the handler that the parent configured."""
        script = tmp_path / "log_in_worker.py"
        script.write_text(
            textwrap.dedent(
                """
                import logging
                import multiprocessing

                from mapillary_tools import utils

                LOG = logging.getLogger("mapillary_tools.test")

                def work(i):
                    LOG.warning("warning from worker %d", i)
                    return i

                if __name__ == "__main__":
                    multiprocessing.set_start_method("fork")
                    utils.configure_logger(logging.getLogger(utils.get_app_name()))
                    list(utils.mp_map_maybe(work, [1], num_processes=1))
                """
            )
        )

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            check=True,
            # The tree under test, not an installed mapillary_tools
            env={**os.environ, "PYTHONPATH": str(Path(utils.__file__).parent.parent)},
        )

        assert result.stderr.count("warning from worker 1") == 1


class TestSanitizeSerial:
    """Tests for sanitize_serial function"""

    def test_none_input(self):
        """Test that None input returns None"""
        assert utils.sanitize_serial(None) is None

    def test_alphanumeric_unchanged(self):
        """Test that alphanumeric strings are unchanged"""
        assert utils.sanitize_serial("ABC123") == "ABC123"
        assert utils.sanitize_serial("abc123xyz") == "abc123xyz"

    def test_removes_whitespace(self):
        """Test that whitespace is removed"""
        assert utils.sanitize_serial("  ABC123  ") == "ABC123"
        assert utils.sanitize_serial("ABC 123") == "ABC123"
        assert utils.sanitize_serial(" A B C ") == "ABC"

    def test_removes_special_characters(self):
        """Test that special characters are removed"""
        assert utils.sanitize_serial("ABC-123") == "ABC123"
        assert utils.sanitize_serial("ABC_123") == "ABC123"
        assert utils.sanitize_serial("ABC/123") == "ABC123"
        assert utils.sanitize_serial("ABC:123") == "ABC123"
        assert utils.sanitize_serial("ABC.123") == "ABC123"

    def test_removes_mixed_special_chars(self):
        """Test removal of various special characters"""
        assert utils.sanitize_serial("SN:ABC-123/XYZ") == "SNABC123XYZ"
        assert utils.sanitize_serial("(ABC)[123]{XYZ}") == "ABC123XYZ"

    def test_empty_after_sanitize_returns_none(self):
        """Test that empty result after sanitization returns None"""
        assert utils.sanitize_serial("") is None
        assert utils.sanitize_serial("   ") is None
        assert utils.sanitize_serial("---") is None
        assert utils.sanitize_serial("!@#$%^&*()") is None

    def test_preserves_case(self):
        """Test that case is preserved"""
        assert utils.sanitize_serial("AbC123xYz") == "AbC123xYz"


def test_md5sum_fp_progress():
    data = b"x" * 1000
    progress: list[int] = []

    md5 = utils.md5sum_fp(io.BytesIO(data), progress=progress.append)

    assert md5.hexdigest() == hashlib.md5(data).hexdigest()
    assert sum(progress) == len(data)
