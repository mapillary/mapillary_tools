import io
import typing as T


class Header(T.NamedTuple):
    # 0 indicates no more boxes
    header_size: int
    type: bytes
    # 0, which is allowed only for a top-level atom, designates the last atom in the file and indicates that the atom extends to the end of the file
    size32: int
    # box size includes header
    box_size: int
    # either -1 or non-negative: data size that can be passed to the read function; -1 indicates open ended
    maxsize: int


class RangeError(Exception):
    pass


def _size_remain(size: int, bound: int) -> int:
    assert 0 <= size and (bound == -1 or 0 <= bound), f"got size={size} bound={bound}"

    if bound == -1:
        return -1

    remaining = bound - size
    if remaining < 0:
        raise RangeError(f"request {size} bytes but {bound} bytes remain")
    return remaining


def parse_box_header(
    stream: T.BinaryIO, maxsize: int = -1, extend_eof: bool = False
) -> Header:
    assert maxsize == -1 or 0 <= maxsize

    def _read(size: int) -> bytes:
        nonlocal maxsize
        size = size if maxsize == -1 else min(size, maxsize)
        assert 0 <= size
        data = stream.read(size)
        maxsize = _size_remain(len(data), maxsize)
        return data

    offset_start = stream.tell()

    # box size
    size32 = int.from_bytes(_read(4), "big", signed=False)

    # type
    box_type = _read(4)

    # large box size that follows box type
    if size32 == 1:
        box_size = int.from_bytes(_read(8), "big", signed=False)
    else:
        box_size = size32

    # header size
    offset_end = stream.tell()
    assert offset_start <= offset_end
    header_size = offset_end - offset_start

    # maxsize
    if extend_eof and size32 == 0:
        # extend to the EoF
        maxsize = maxsize
    else:
        data_size = _size_remain(header_size, box_size)
        _size_remain(data_size, maxsize)
        maxsize = data_size

    return Header(
        header_size=header_size,
        type=box_type,
        size32=size32,
        box_size=box_size,
        maxsize=maxsize,
    )


def parse_boxes(
    stream: T.BinaryIO,
    maxsize: int = -1,
    extend_eof: bool = False,
) -> T.Generator[T.Tuple[Header, T.BinaryIO], None, None]:
    assert maxsize == -1 or 0 <= maxsize

    while True:
        offset = stream.tell()
        header = parse_box_header(stream, maxsize=maxsize, extend_eof=extend_eof)

        if not header.header_size:
            break

        yield header, stream

        # adjust offset and maxsize for the next box parsing
        if extend_eof and header.size32 == 0:
            if maxsize == -1:
                stream.seek(0, io.SEEK_END)
            else:
                stream.seek(offset + maxsize, io.SEEK_SET)
            maxsize = 0
        else:
            stream.seek(offset + header.box_size, io.SEEK_SET)
            maxsize = _size_remain(header.box_size, maxsize)

        assert offset < stream.tell(), "must move"


def parse_boxes_recursive(
    stream: T.BinaryIO,
    maxsize: int = -1,
    depth: int = 0,
    box_list_types: T.Optional[T.Set[bytes]] = None,
) -> T.Generator[T.Tuple[Header, int, T.BinaryIO], None, None]:
    assert maxsize == -1 or 0 <= maxsize

    if box_list_types is None:
        box_list_types = set()

    for header, box in parse_boxes(stream, maxsize=maxsize, extend_eof=depth == 0):
        offset = box.tell()
        yield header, depth, stream
        if header.type in box_list_types:
            box.seek(offset, io.SEEK_SET)
            yield from parse_boxes_recursive(
                stream,
                maxsize=header.maxsize,
                depth=depth + 1,
                box_list_types=box_list_types,
            )


if __name__ == "__main__":
    import sys, os
    from .. import utils

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
        b"gmhd",
    }

    def _parse_file(path: str):
        with open(path, "rb") as fp:
            for h, d, s in parse_boxes_recursive(fp, box_list_types=box_list_types):
                margin = "\t" * d
                try:
                    utfh = h.type.decode("utf8")
                except UnicodeDecodeError:
                    utfh = str(h)
                header = f"{utfh} {h.box_size}:"
                if h.type in box_list_types:
                    print(margin, header)
                else:
                    print(margin, header, s.read(h.maxsize)[:32])

    for path in sys.argv[1:]:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                _parse_file(p)
        else:
            _parse_file(path)
