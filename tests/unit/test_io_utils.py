import io
import random

from mapillary_tools.geotag.io_utils import ChainedIO, SlicedIO


def test_chained():
    data = b"helloworldworldfoobarworld"
    c = io.BytesIO(data)
    s = ChainedIO(
        [
            io.BytesIO(b"hello"),
            ChainedIO([io.BytesIO(b"world")]),
            ChainedIO(
                [
                    ChainedIO([io.BytesIO(b""), io.BytesIO(b"")]),
                    io.BytesIO(b"world"),
                    io.BytesIO(b"foo"),
                    ChainedIO([io.BytesIO(b"")]),
                ]
            ),
            ChainedIO([io.BytesIO(b"")]),
            ChainedIO([io.BytesIO(b"bar")]),
            ChainedIO(
                [
                    SlicedIO(io.BytesIO(data), 5, 5),
                    ChainedIO([io.BytesIO(b"")]),
                ]
            ),
        ]
    )

    assert s.seek(0) == 0
    assert c.seek(0) == 0
    assert s.read() == c.read()

    assert s.seek(2, io.SEEK_CUR) == len(data) + 2
    assert c.seek(2, io.SEEK_CUR) == len(data) + 2
    assert s.read() == c.read()

    assert s.seek(6) == 6
    assert c.seek(6) == 6
    assert s.read() == c.read()

    assert s.seek(2, io.SEEK_END) == len(data) + 2
    assert c.seek(2, io.SEEK_END) == len(data) + 2
    assert s.read() == c.read()

    assert s.seek(0) == 0
    assert c.seek(0) == 0
    assert s.read(1) == b"h"
    assert s.read(1000) == data[1:]
    assert s.read() == b""
    assert s.read(1) == b""

    assert s.seek(0, io.SEEK_END) == len(data)
    assert c.seek(0, io.SEEK_END) == len(data)

    c.seek(0)
    s.seek(0)
    for _ in range(10000):
        whence = random.choice([io.SEEK_SET, io.SEEK_CUR, io.SEEK_END])
        offset = random.randint(0, 30)
        assert s.tell() == c.tell()
        thrown_x = None
        try:
            x = s.seek(offset, whence)
        except ValueError as ex:
            thrown_x = ex
        thrown_y = None
        try:
            y = c.seek(offset, whence)
        except ValueError as ex:
            thrown_y = ex
        assert (thrown_x is not None and thrown_y is not None) or (
            thrown_x is None and thrown_y is None
        ), (thrown_x, thrown_y, whence, offset)
        if not thrown_x:
            assert (
                x == y
            ), f"whence={whence} offset={offset} x={x} y={y} {s.tell()} {c.tell()}"

        n = random.randint(-1, 20)
        assert s.read(n) == c.read(n), f"n={n}"
        assert s.tell() == c.tell()


def test_sliced():
    s = io.BytesIO(b"helloworldfoo")
    sliced = SlicedIO(s, 5, 5)
    c = io.BytesIO(b"world")

    for _ in range(10000):
        whence = random.choice([io.SEEK_SET, io.SEEK_CUR, io.SEEK_END])
        offset = random.randint(-10, 10)
        thrown_x = None
        try:
            x = sliced.seek(offset, whence)
        except ValueError as ex:
            thrown_x = ex
        thrown_y = None
        try:
            y = c.seek(offset, whence)
        except ValueError as ex:
            thrown_y = ex
        assert (thrown_x is not None and thrown_y is not None) or (
            thrown_x is None and thrown_y is None
        ), (thrown_x, thrown_y, whence, offset)
        if not thrown_x:
            assert x == y

        n = random.randint(-1, 20)
        assert sliced.read(n) == c.read(n)
        assert sliced.tell() == c.tell()


def test_truncate():
    c = io.BytesIO(b"helloworld")
    c.truncate(3)
    assert c.read() == b"hel"
    s = SlicedIO(c, 1, 5)
    assert s.read() == b"el"
    assert s.read() == b""
