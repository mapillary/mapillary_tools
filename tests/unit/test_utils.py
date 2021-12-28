from mapillary_tools import utils


def test_filter():
    images = [
        "foo/bar/hello.mp4/hello_123.jpg",
        "/hello.mp4/hello_123.jpg",
        "foo/bar/hello/hello_123.jpg",
        "/hello.mp4/hell_123.jpg",
    ]
    r = utils.filter_video_samples(images, "hello.mp4")
    assert r == ["foo/bar/hello.mp4/hello_123.jpg", "/hello.mp4/hello_123.jpg"]
