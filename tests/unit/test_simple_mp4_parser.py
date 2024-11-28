import io
import typing

from mapillary_tools.mp4 import (
    construct_mp4_parser as cparser,
    simple_mp4_parser as sparser,
)


def _construct_parser(data: bytes):
    return cparser.MP4ParserConstruct.parse_boxlist(data)


def _parse(data: bytes):
    box_list_types = {
        b"moov",
        b"moof",
        b"traf",
        b"mvex",
        b"trak",
        b"mdia",
        b"minf",
        b"dinf",
        b"stbl",
        b"schi",
    }
    consumed_size = 0
    ret = []
    for h, _d, s in sparser.parse_boxes_recursive(
        io.BytesIO(data), box_list_types=box_list_types
    ):
        box_data = s.read(h.maxsize)
        ret.append((h, box_data))
        if h.type not in box_list_types:
            consumed_size += len(box_data)
        consumed_size += h.header_size
        # testing random seek in the iterator
        s.seek(0, io.SEEK_SET)
    assert consumed_size == len(data)
    return ret


def _assert_box_type(
    data: bytes,
    parsed: typing.List[typing.Tuple[sparser.Header, bytes]],
    box_type: bytes,
):
    assert 1 == len(parsed)
    header, box_data = parsed[0]
    assert header.type == box_type
    assert len(box_data) + header.header_size == len(data)
    if header.box_size != 0:
        assert header.box_size == len(data)


def test_parse_box_header():
    s = io.BytesIO(b"hello")
    header = sparser.parse_box_header(s, maxsize=0)
    assert header.header_size == 0
    assert header.box_size == 0
    assert header.type == b""
    assert header.maxsize == 0
    assert s.tell() == 0


def test_empty_parse():
    parsed = _parse(b"")
    assert not len(parsed)


def test_zeros_parse():
    data = b"\x00\x00\x00\x00"
    parsed = _parse(data)
    _assert_box_type(data, parsed, b"")


def test_zeros_parse_2():
    parsed = _parse(b"\x00\x00\x00\x00hellworld")
    assert len(parsed) == 1
    assert parsed[0][0].type == b"hell"
    assert parsed[0][1] == b"world"
    cr = _construct_parser(b"\x00\x00\x00\x00hellworld")[0]
    assert cr["type"] == b"hell"
    assert cr["data"] == b"world"


def test_zeros_parse_3():
    parsed = _parse(b"\x00\x00\x00\x01hell\x00\x00\x00\x00\x00\x00\x00\x15world")
    assert len(parsed) == 1
    assert parsed[0][0].type == b"hell"
    assert parsed[0][1] == b"world"
    cr = _construct_parser(b"\x00\x00\x00\x01hell\x00\x00\x00\x00\x00\x00\x00\x15world")


def test_tenc_parse():
    data = b"\x00\x00\x00 tenc\x00\x00\x00\x00\x00\x00\x01\x083{\x96C!\xb6CU\x9eY>\xcc\xb4l~\xf7"
    parsed = _parse(data)
    _assert_box_type(data, parsed, b"tenc")
    cr = _construct_parser(data)[0]
    assert cr["type"] == b"tenc"
    assert (
        cr["data"]
        == b"\x00\x00\x00\x00\x00\x00\x01\x083{\x96C!\xb6CU\x9eY>\xcc\xb4l~\xf7"
    )


def test_ftyp_parse():
    data = b"\x00\x00\x00\x18ftypiso5\x00\x00\x00\x01iso5avc1"
    parsed = _parse(data)
    _assert_box_type(data, parsed, b"ftyp")
    _construct_parser(data)


def test_mdhd_parse():
    data = b"\x00\x00\x00\x20mdhd\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0fB@\x00\x00\x00\x00U\xc4\x00\x00"
    parsed = _parse(data)
    _assert_box_type(data, parsed, b"mdhd")
    _construct_parser(data)


def test_moov_parse():
    data = (
        b"\x00\x00\x00\x60moov"
        b"\x00\x00\x00\x58trak"
        b"\x00\x00\x00\x10mehd\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x20trex\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x20box1\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x20box2\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    )
    parsed = _parse(data)
    assert {b"moov", b"trak", b"mehd", b"trex", b"box1", b"box2"} == set(
        header.type for header, _ in parsed
    )
    cr = _construct_parser(data)
    first_box = cr[0]
    assert first_box["type"] == b"moov"
    assert first_box["data"][0]["type"] == b"trak"
    assert first_box["data"][0]["data"][0]["type"] == b"mehd"
    assert (
        first_box["data"][0]["data"][0]["data"] == b"\x00\x00\x00\x00\x00\x00\x00\x00"
    )
    assert first_box["data"][0]["data"][1]["type"] == b"trex"
    assert (
        first_box["data"][0]["data"][1]["data"]
        == b"\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    )
    assert first_box["data"][0]["data"][2]["type"] == b"box1"
    assert (
        first_box["data"][0]["data"][2]["data"]
        == b"\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    )


def test_eof_parse():
    data = b"\x00\x00\x00\x18ftypiso5\x00\x00\x00\x01iso5avc1"
    data += b"\x00\x00\x00\x00box1iso5\x00\x00\x00\x01iso5avc1"
    data += b"\x00\x00\x00\x18box2iso5\x00\x00\x00\x01iso5avc1"
    parsed = _parse(data)
    assert {b"ftyp", b"box1"} == set(header.type for header, _ in parsed)
    _construct_parser(data)


def test_wide_parse():
    data = b"\x00\x00\x00\x10mdat"
    data += b"\x00\x00\x00\x18wide"
    data += b"\x00\x00\x00\x08box1"
    data += b"\x00\x00\x00\x08box2"
    parsed = _parse(data)
    assert {b"mdat", b"box1", b"box2"} == set(header.type for header, _ in parsed)
    cr = _construct_parser(data)
    assert {b"mdat", b"box1", b"box2"} == set(r["type"] for r in cr)


def test_dref():
    data = (
        b"\x00"  # version
        + b"\x00\x00\x00"  # flags
        + b"\x00\x00\x00\x01"  # entry_count
        + b"\x00\x00\x00\x0c"  # size
        + b"alis"  # type
        + b"\x00"  # version
        + b"\x00\x00\x01"  # flags
    )
    actual = cparser.DataReferenceBox.parse(data)
    assert 0 == actual["version"]
    assert 0 == actual["flags"]
    assert b"alis" == actual["entries"][0]["type"]
    assert b"\x00\x00\x00\x01" == actual["entries"][0]["data"]
    assert {"type": b"alis", "data": b"\x00\x00\x00\x01"} == actual["entries"][0]


def test_dref2():
    data = (
        b"\x00"  # version
        + b"\x00\x00\x00"  # flags
        + b"\x00\x00\x00\x01"  # entry_count
        + b"\x00\x00\x00\x0c"  # size
        + b"url "  # type
        + b"\x00"  # version
        + b"\x00\x00\x01"  # flags
    )
    actual = cparser.DataReferenceBox.parse(data)
    assert 0 == actual["version"]
    assert 0 == actual["flags"]
    assert b"url " == actual["entries"][0]["type"]
    assert 1 == actual["entries"][0]["data"]["flags"]
    assert b"" == actual["entries"][0]["data"]["data"]
