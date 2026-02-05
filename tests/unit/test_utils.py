# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import sys
from pathlib import Path

import py.path
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
    assert {
        Path("hello.mp4"): [
            Path("foo/hello.mp4/hello_123.jpg"),
            Path("foo/hello.mp4/hello_.jpg"),
        ],
        Path("world.mp4"): [Path("world.mp4/world_123.jpg")],
    } == image_samples_by_video_path


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
