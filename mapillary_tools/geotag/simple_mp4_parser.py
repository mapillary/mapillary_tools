import datetime
import io
import typing as T

import construct as C


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


def parse_path(
    stream: T.BinaryIO, path: T.List[bytes], maxsize: int = -1, depth: int = 0
) -> T.Generator[T.Tuple[Header, T.BinaryIO], None, None]:
    if not path:
        return
    for h, s in parse_boxes(stream, maxsize=maxsize, extend_eof=depth == 0):
        if h.type == path[0]:
            if len(path) == 1:
                yield h, s
            else:
                yield from parse_path(s, path[1:], maxsize=h.maxsize, depth=depth + 1)


UNITY_MATRIX = [0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000]

TrackHeaderBox = C.Struct(
    # "type" / C.Const(b"tkhd"),
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 1),
    "creation_time"
    / C.Default(C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub), 0),
    "modification_time"
    / C.Default(C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub), 0),
    "track_ID" / C.Default(C.Int32ub, 1),
    C.Padding(4),
    "duration" / C.Default(C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub), 0),
    C.Padding(8),
    "layer" / C.Default(C.Int16sb, 0),
    "alternate_group" / C.Default(C.Int16sb, 0),
    "volume" / C.Default(C.Int16sb, 0),
    C.Padding(2),
    "matrix" / C.Default(C.Array(9, C.Int32sb), UNITY_MATRIX),
    "width" / C.Default(C.Int32ub, 0),
    "height" / C.Default(C.Int32ub, 0),
)

MediaHeaderBox = C.Struct(
    # "type" / C.Const(b"mdhd"),
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Const(0, C.Int24ub),
    "creation_time" / C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub),
    "modification_time" / C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub),
    "timescale" / C.Int32ub,
    "duration" / C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub),
    "language" / C.Int16ub,
    C.Padding(2),
)


SampleEntryBox = C.Prefixed(
    C.Int32ub,
    C.Struct(
        "format" / C.Bytes(4),
        C.Padding(6),
        "data_reference_index" / C.Default(C.Int16ub, 1),
        "data" / C.GreedyBytes,
    ),
    includelength=True,
)

SampleDescriptionBox = C.Struct(
    # "type" / C.Const(b"stsd"),
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Const(0, C.Int24ub),
    "entries" / C.PrefixedArray(C.Int32ub, SampleEntryBox),
)


SampleSizeBox = C.Struct(
    # "type" / C.Const(b"stsz"),
    "version" / C.Int8ub,
    "flags" / C.Const(0, C.Int24ub),
    # If this field is set to 0, then the samples have different sizes, and those sizes are stored in the sample size table.
    "sample_size" / C.Int32ub,
    "sample_count" / C.Int32ub,
    "entry_sizes"
    / C.If(C.this.sample_size == 0, C.Array(C.this.sample_count, C.Int32ub)),
)

ChunkOffsetBox = C.Struct(
    # "type" / C.Const(b"stco"),
    "version" / C.Const(0, C.Int8ub),
    "flags" / C.Const(0, C.Int24ub),
    "entries"
    / C.Default(
        C.PrefixedArray(
            C.Int32ub,
            C.Struct(
                "chunk_offset" / C.Int32ub,
            ),
        ),
        [],
    ),
)

ChunkLargeOffsetBox = C.Struct(
    # "type" / C.Const(b"co64"),
    "version" / C.Const(0, C.Int8ub),
    "flags" / C.Const(0, C.Int24ub),
    "entries"
    / C.PrefixedArray(
        C.Int32ub,
        C.Struct(
            "chunk_offset" / C.Int64ub,
        ),
    ),
)

TimeToSampleBox = C.Struct(
    # "type" / C.Const(b"stts"),
    "version" / C.Const(0, C.Int8ub),
    "flags" / C.Const(0, C.Int24ub),
    "entries"
    / C.Default(
        C.PrefixedArray(
            C.Int32ub,
            C.Struct(
                "sample_count" / C.Int32ub,
                "sample_delta" / C.Int32ub,
            ),
        ),
        [],
    ),
)

SampleToChunkBox = C.Struct(
    # "type" / C.Const(b"stsc"),
    "version" / C.Const(0, C.Int8ub),
    "flags" / C.Const(0, C.Int24ub),
    "entries"
    / C.Default(
        C.PrefixedArray(
            C.Int32ub,
            C.Struct(
                "first_chunk" / C.Int32ub,
                "samples_per_chunk" / C.Int32ub,
                "sample_description_index" / C.Int32ub,
            ),
        ),
        [],
    ),
)


class Sample(T.NamedTuple):
    description: bytes
    offset: int
    size: int
    delta: T.Union[int, float]


def extract_samples(
    descriptions: T.List,
    sizes: T.List[int],
    chunk_entries: T.List,
    offsets: T.List[int],
    time_deltas: T.List[int],
) -> T.Generator[Sample, None, None]:
    assert chunk_entries, "empty chunk entries"
    assert len(sizes) == len(
        time_deltas
    ), f"sample sizes {len(sizes)} != sample times {len(time_deltas)}"

    sample_idx = 0
    chunk_idx = 0

    for entry_idx, entry in enumerate(chunk_entries):
        if entry_idx + 1 < len(chunk_entries):
            nbr_chunks = chunk_entries[entry_idx + 1].first_chunk - entry.first_chunk
        else:
            nbr_chunks = 1
        for _ in range(nbr_chunks):
            sample_offset = offsets[chunk_idx]
            for _ in range(entry.samples_per_chunk):
                yield Sample(
                    description=descriptions[entry.sample_description_index - 1],
                    offset=sample_offset,
                    size=sizes[sample_idx],
                    delta=time_deltas[sample_idx],
                )
                sample_offset += sizes[sample_idx]
                sample_idx += 1
            chunk_idx += 1

    # If all the chunks have the same number of samples per chunk and use the same sample description, this table has one entry.
    while sample_idx < len(time_deltas):
        for _ in range(chunk_entries[-1].samples_per_chunk):
            sample_offset = offsets[chunk_idx]
            yield Sample(
                description=descriptions[
                    chunk_entries[-1].sample_description_index - 1
                ],
                offset=sample_offset,
                size=sizes[sample_idx],
                delta=time_deltas[sample_idx],
            )
            sample_offset += sizes[sample_idx]
            sample_idx += 1
        chunk_idx += 1


def parse_samples_from_stbl(
    stbl: T.BinaryIO, maxsize: int = -1
) -> T.Generator[Sample, None, None]:
    descriptions = []
    sizes = []
    offsets = []
    chunk_entries = []
    time_deltas: T.List[int] = []

    for h, s in parse_boxes(stbl, maxsize=maxsize, extend_eof=False):
        if h.type == b"stsd":
            box = SampleDescriptionBox.parse(s.read(h.maxsize))
            descriptions = list(box.entries)
        elif h.type == b"stsz":
            box = SampleSizeBox.parse(s.read(h.maxsize))
            if box.sample_size == 0:
                sizes = list(box.entry_sizes)
            else:
                sizes = [box.sample_size for _ in range(box.sample_count)]
        elif h.type == b"stco":
            box = ChunkOffsetBox.parse(s.read(h.maxsize))
            offsets = [entry.chunk_offset for entry in box.entries]
        elif h.type == b"co64":
            box = ChunkLargeOffsetBox.parse(s.read(h.maxsize))
            offsets = [entry.chunk_offset for entry in box.entries]
        elif h.type == b"stsc":
            box = SampleToChunkBox.parse(s.read(h.maxsize))
            chunk_entries = list(box.entries)
        elif h.type == b"stts":
            box = TimeToSampleBox.parse(s.read(h.maxsize))
            time_deltas = []
            accumulated_delta = 0
            for entry in box.entries:
                for _ in range(entry.sample_count):
                    # DT(n + 1) = DT(n) + STTS(n)
                    time_deltas.append(accumulated_delta)
                    accumulated_delta += entry.sample_delta

    yield from extract_samples(descriptions, sizes, chunk_entries, offsets, time_deltas)


def parse_samples_from_trak(
    trak: T.BinaryIO, maxsize: int = -1
) -> T.Generator[Sample, None, None]:
    offset = trak.tell()

    mdhd = None
    for h, s in parse_path(trak, [b"mdia", b"mdhd"], maxsize=maxsize):
        mdhd = MediaHeaderBox.parse(s.read(h.maxsize))
        break
    assert mdhd is not None, "mdhd is required but not found"

    trak.seek(offset, io.SEEK_SET)
    for h, s in parse_path(trak, [b"mdia", b"minf", b"stbl"], maxsize=maxsize):
        for sample in parse_samples_from_stbl(s, maxsize=h.maxsize):
            yield Sample(
                description=sample.description,
                offset=sample.offset,
                size=sample.size,
                delta=sample.delta / mdhd.timescale,
            )
        break


_DT_1904 = datetime.datetime.utcfromtimestamp(0).replace(year=1904)


def to_datetime(seconds_since_1904: int) -> datetime.datetime:
    """
    Convert seconds since midnight, Jan. 1, 1904, in UTC time
    """
    return _DT_1904 + datetime.timedelta(seconds=seconds_since_1904)
