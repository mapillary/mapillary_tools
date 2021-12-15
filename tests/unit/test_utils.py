from mapillary_tools import image_log


def test_filter():
    images = [
        "foo/bar/hello.mp4/hello_123.jpg",
        "/hello.mp4/hello_123.jpg",
        "foo/bar/hello/hello_123.jpg",
        "/hello.mp4/hell_123.jpg",
    ]
    r = image_log.filter_video_samples(images, "hello.mp4")
    assert r == ["foo/bar/hello.mp4/hello_123.jpg", "/hello.mp4/hello_123.jpg"]
