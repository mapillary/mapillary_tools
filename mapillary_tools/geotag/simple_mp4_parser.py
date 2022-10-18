# pyre-ignore-all-errors[5, 16, 21, 24, 58]

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


class ParsingError(Exception):
    """Base class for exceptions in this module."""

    pass


class RangeError(ParsingError):
    """Raise when less bytes available than expected"""

    pass


class BoxNotFoundError(ParsingError):
    """Raise when a required box is not found"""

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


def parse_path(
    stream: T.BinaryIO,
    path: T.Sequence[T.Union[bytes, T.Sequence[bytes]]],
    maxsize: int = -1,
    depth: int = 0,
) -> T.Generator[T.Tuple[Header, T.BinaryIO], None, None]:
    if not path:
        return

    for h, s in parse_boxes(stream, maxsize=maxsize, extend_eof=depth == 0):
        if isinstance(path[0], bytes):
            first_paths = {path[0]}
        else:
            first_paths = set(path[0])
        if h.type in first_paths:
            if len(path) == 1:
                yield h, s
            else:
                yield from parse_path(s, path[1:], maxsize=h.maxsize, depth=depth + 1)


def _parse_path_first(
    stream: T.BinaryIO, path: T.List[bytes], maxsize: int = -1, depth: int = 0
) -> T.Optional[T.Tuple[Header, T.BinaryIO]]:
    if not path:
        return None
    for h, s in parse_boxes(stream, maxsize=maxsize, extend_eof=depth == 0):
        if h.type == path[0]:
            if len(path) == 1:
                return h, s
            else:
                return _parse_path_first(
                    s, path[1:], maxsize=h.maxsize, depth=depth + 1
                )
    return None


def parse_box_path_firstx(
    stream: T.BinaryIO, path: T.List[bytes], maxsize: int = -1
) -> T.Tuple[Header, T.BinaryIO]:
    # depth=1 will disable EoF extension
    parsed = _parse_path_first(stream, path, maxsize=maxsize, depth=1)
    if parsed is None:
        raise BoxNotFoundError(f"unable find box at path {path}")
    return parsed


def parse_mp4_data_first(
    stream: T.BinaryIO, path: T.List[bytes], maxsize: int = -1
) -> T.Optional[bytes]:
    # depth=0 will enable EoF extension
    parsed = _parse_path_first(stream, path, maxsize=maxsize, depth=0)
    if parsed is None:
        return None
    h, s = parsed
    return s.read(h.maxsize)


def parse_mp4_data_firstx(
    stream: T.BinaryIO, path: T.List[bytes], maxsize: int = -1
) -> bytes:
    data = parse_mp4_data_first(stream, path, maxsize=maxsize)
    if data is None:
        raise BoxNotFoundError(f"unable find box at path {path}")
    return data


def parse_box_data_first(
    stream: T.BinaryIO, path: T.List[bytes], maxsize: int = -1
) -> T.Optional[bytes]:
    # depth=1 will disable EoF extension
    parsed = _parse_path_first(stream, path, maxsize=maxsize, depth=1)
    if parsed is None:
        return None
    h, s = parsed
    return s.read(h.maxsize)


def parse_box_data_firstx(
    stream: T.BinaryIO, path: T.List[bytes], maxsize: int = -1
) -> bytes:
    data = parse_box_data_first(stream, path, maxsize=maxsize)
    if data is None:
        raise BoxNotFoundError(f"unable find box at path {path}")
    return data
