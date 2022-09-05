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
    tmpdir.join("foo").join("world.TIFF").open("wb").close()
    tmpdir.join("foo").join("world.ZIP").open("wb").close()
    tmpdir.join("foo").join("world.mp4").open("wb").close()
    tmpdir.join("foo").join("world.MP4").open("wb").close()
    tmpdir.join("foo").join(".jpg").open("wb").close()
    tmpdir.join("foo").join(".png").open("wb").close()
    tmpdir.join("foo").join(".zip").open("wb").close()
    tmpdir.join("foo").join(".MP4").open("wb").close()
    tmpdir.join("foo").mkdir(".git")
    # TODO: life too short to test for windows
    if not sys.platform.startswith("win"):
        assert {"foo/world.TIFF", "foo/hello.jpg", "foo/.foo"} == set(
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
        assert {"foo/world.zip", "foo/.foo", "foo/world.ZIP"} == set(
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
                    Path(tmpdir.join("foo").join(".foo")),
                    Path(tmpdir.join("foo").join("../foo")),
                ]
            )
        )
        # some platform filenames are case sensitive?
        assert (
            {"foo/world.MP4", "foo/.foo"} == actual
            or {
                "foo/world.mp4",
                "foo/world.MP4",
                "foo/.foo",
            }
            == actual
            or {"foo/world.mp4", "foo/.foo"} == actual
        )
