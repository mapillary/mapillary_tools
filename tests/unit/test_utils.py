from pathlib import Path

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
