import datetime
import io
import typing as T

import construct as C


UINT32_MAX = 2**32 - 1


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


def parse_path_first(
    stream: T.BinaryIO, path: T.List[bytes], maxsize: int = -1, depth: int = 0
) -> T.Optional[T.Tuple[Header, T.BinaryIO]]:
    if not path:
        return None
    for h, s in parse_boxes(stream, maxsize=maxsize, extend_eof=depth == 0):
        if h.type == path[0]:
            if len(path) == 1:
                return h, s
            else:
                return parse_path_first(s, path[1:], maxsize=h.maxsize, depth=depth + 1)
    return None


def parse_path_firstx(
    stream: T.BinaryIO, path: T.List[bytes], maxsize: int = -1, depth: int = 0
) -> T.Tuple[Header, T.BinaryIO]:
    parsed = parse_path_first(stream, path, maxsize=maxsize, depth=depth)
    assert parsed is not None, f"unable find box at path {path}"
    return parsed


_UNITY_MATRIX = [0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000]

# moov -> trak -> tkhd
TrackHeaderBox = C.Struct(
    # "type" / C.Const(b"tkhd"),
    "version" / C.Default(C.Int8ub, 0),
    # Track_enabled: Indicates that the track is enabled. Flag value is 0x000001.
    # A disabled track (the low bit is zero) is treated as if it were not present.
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
    "matrix" / C.Default(C.Array(9, C.Int32sb), _UNITY_MATRIX),
    "width" / C.Default(C.Int32ub, 0),
    "height" / C.Default(C.Int32ub, 0),
)

# moov -> trak -> mdia -> mdhd
# Box Type: ‘mdhd’
# Container: Media Box (‘mdia’) Mandatory: Yes
# Quantity: Exactly one
MediaHeaderBox = C.Struct(
    # "type" / C.Const(b"mdhd"),
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
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

# moov -> trak -> mdia -> minf -> stbl -> stsd
# BoxTypes: ‘stsd’
# Container: Sample Table Box (‘stbl’) Mandatory: Yes
# Quantity: Exactly one
SampleDescriptionBox = C.Struct(
    # "type" / C.Const(b"stsd"),
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    "entries" / C.PrefixedArray(C.Int32ub, SampleEntryBox),
)


# moov -> trak -> mdia -> minf -> stbl -> stsz
# Box Type: ‘stsz’, ‘stz2’
# Container: Sample Table Box (‘stbl’) Mandatory: Yes
# Quantity: Exactly one variant must be present
SampleSizeBox = C.Struct(
    # "type" / C.Const(b"stsz"),
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    # If this field is set to 0, then the samples have different sizes, and those sizes are stored in the sample size table.
    "sample_size" / C.Int32ub,
    "sample_count" / C.Int32ub,
    "entries"
    / C.IfThenElse(
        C.this.sample_size == 0,
        C.Array(C.this.sample_count, C.Int32ub),
        C.Array(0, C.Int32ub),
    ),
)

# moov -> trak -> stbl -> stco
# Box Type: ‘stco’, ‘co64’
# Container: Sample Table Box (‘stbl’) Mandatory: Yes
# Quantity: Exactly one variant must be present
ChunkOffsetBox = C.Struct(
    # "type" / C.Const(b"stco"),
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    "entries"
    / C.Default(
        C.PrefixedArray(
            C.Int32ub,
            # chunk offset
            C.Int32ub,
        ),
        [],
    ),
)

# moov -> trak -> mdia -> minf -> stbl -> co64
ChunkLargeOffsetBox = C.Struct(
    # "type" / C.Const(b"co64"),
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    "entries"
    / C.PrefixedArray(
        C.Int32ub,
        # chunk offset
        C.Int64ub,
    ),
)

# moov -> trak -> mdia -> minf -> stbl -> stts
# Box Type: ‘stts’
# Container: Sample Table Box (‘stbl’) Mandatory: Yes
# Quantity: Exactly one
TimeToSampleBox = C.Struct(
    # "type" / C.Const(b"stts"),
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
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

# moov -> trak -> mdia -> minf -> stbl -> stsc
# Box Type: ‘stsc’
# Container: Sample Table Box (‘stbl’) Mandatory: Yes
# Quantity: Exactly one
SampleToChunkBox = C.Struct(
    # "type" / C.Const(b"stsc"),
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
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

# moov -> trak -> mdia -> minf -> stbl -> stss
# Box Type: ‘stss’
# Container: Sample Table Box (‘stbl’) No
# Mandatory: No
# Quantity: Zero or one

# This box provides a compact marking of the random access points within the stream. The table is arranged in strictly increasing order of sample number.
# If the sync sample box is not present, every sample is a random access point.
SyncSampleBox = C.Struct(
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    "entries"
    / C.Default(
        C.PrefixedArray(
            C.Int32ub,
            C.Int32ub,
        ),
        [],
    ),
)


class RawSample(T.NamedTuple):
    # 1-based index
    description_idx: int
    # sample offset
    offset: int
    # sample size
    size: int
    # sample_delta read from stts entries,
    # i.e. STTS(n) in the forumula DT(n+1) = DT(n) + STTS(n)
    timedelta: int
    # if it is a sync sample
    is_sync: bool


class Sample(T.NamedTuple):
    # reference to the sample description
    description: T.Any
    # sample offset
    offset: int
    # sample size
    size: int
    # accumulated sample_delta,
    # i.e. DT(n) in the forumula DT(n+1) = DT(n) + STTS(n)
    time_offset: T.Union[int, float]


def extract_raw_samples(
    sizes: T.List[int],
    chunk_entries: T.List,
    chunk_offsets: T.List[int],
    timedeltas: T.List[int],
    syncs: T.Optional[T.Set[int]],
) -> T.Generator[RawSample, None, None]:
    if not chunk_entries:
        return

    assert len(sizes) == len(
        timedeltas
    ), f"sample sizes {len(sizes)} and sample times {len(timedeltas)} must have equal length"

    sample_idx = 0
    chunk_idx = 0

    for entry_idx, entry in enumerate(chunk_entries):
        if entry_idx + 1 < len(chunk_entries):
            nbr_chunks = chunk_entries[entry_idx + 1].first_chunk - entry.first_chunk
        else:
            nbr_chunks = 1
        for _ in range(nbr_chunks):
            sample_offset = chunk_offsets[chunk_idx]
            for _ in range(entry.samples_per_chunk):
                is_sync = syncs is None or (sample_idx + 1) in syncs
                yield RawSample(
                    description_idx=entry.sample_description_index,
                    offset=sample_offset,
                    size=sizes[sample_idx],
                    timedelta=timedeltas[sample_idx],
                    is_sync=is_sync,
                )
                sample_offset += sizes[sample_idx]
                sample_idx += 1
            chunk_idx += 1

    # If all the chunks have the same number of samples per chunk and use the same sample description,
    # this table has one entry.
    while sample_idx < len(timedeltas):
        sample_offset = chunk_offsets[chunk_idx]
        for _ in range(chunk_entries[-1].samples_per_chunk):
            is_sync = syncs is None or (sample_idx + 1) in syncs
            yield RawSample(
                description_idx=chunk_entries[-1].sample_description_index,
                offset=sample_offset,
                size=sizes[sample_idx],
                timedelta=timedeltas[sample_idx],
                is_sync=is_sync,
            )
            sample_offset += sizes[sample_idx]
            sample_idx += 1
        chunk_idx += 1


def extract_samples(
    descriptions: T.List,
    raw_samples: T.Iterator[RawSample],
) -> T.Generator[Sample, None, None]:
    acc_delta = 0
    for raw_sample in raw_samples:
        yield Sample(
            description=descriptions[raw_sample.description_idx - 1],
            offset=raw_sample.offset,
            size=raw_sample.size,
            time_offset=acc_delta,
        )
        acc_delta += raw_sample.timedelta


def parse_raw_samples_from_stbl(
    stbl: T.BinaryIO, maxsize: int = -1
) -> T.Tuple[T.List[bytes], T.Generator[RawSample, None, None]]:
    descriptions = []
    sizes = []
    chunk_offsets = []
    chunk_entries = []
    timedeltas: T.List[int] = []
    syncs: T.Optional[T.Set[int]] = None

    for h, s in parse_boxes(stbl, maxsize=maxsize, extend_eof=False):
        if h.type == b"stsd":
            box = SampleDescriptionBox.parse(s.read(h.maxsize))
            descriptions = list(box.entries)
        elif h.type == b"stsz":
            box = SampleSizeBox.parse(s.read(h.maxsize))
            if box.sample_size == 0:
                sizes = list(box.entries)
            else:
                sizes = [box.sample_size for _ in range(box.sample_count)]
        elif h.type == b"stco":
            box = ChunkOffsetBox.parse(s.read(h.maxsize))
            chunk_offsets = list(box.entries)
        elif h.type == b"co64":
            box = ChunkLargeOffsetBox.parse(s.read(h.maxsize))
            chunk_offsets = list(box.entries)
        elif h.type == b"stsc":
            box = SampleToChunkBox.parse(s.read(h.maxsize))
            chunk_entries = list(box.entries)
        elif h.type == b"stts":
            timedeltas = []
            box = TimeToSampleBox.parse(s.read(h.maxsize))
            for entry in box.entries:
                for _ in range(entry.sample_count):
                    timedeltas.append(entry.sample_delta)
        elif h.type == b"stss":
            box = SyncSampleBox.parse(s.read(h.maxsize))
            syncs = set(box.entries)

    raw_samples = extract_raw_samples(
        sizes, chunk_entries, chunk_offsets, timedeltas, syncs
    )
    return descriptions, raw_samples


def parse_samples_from_stbl(
    stbl: T.BinaryIO, maxsize: int = -1
) -> T.Generator[Sample, None, None]:
    descriptions, raw_samples = parse_raw_samples_from_stbl(stbl, maxsize)
    yield from extract_samples(descriptions, raw_samples)


def parse_samples_from_trak(
    trak: T.BinaryIO, maxsize: int = -1
) -> T.Generator[Sample, None, None]:
    trak_start_offset = trak.tell()

    h, s = parse_path_firstx(trak, [b"mdia", b"mdhd"], maxsize=maxsize)
    mdhd = MediaHeaderBox.parse(s.read(h.maxsize))

    trak.seek(trak_start_offset, io.SEEK_SET)
    h, s = parse_path_firstx(trak, [b"mdia", b"minf", b"stbl"], maxsize=maxsize)
    for sample in parse_samples_from_stbl(s, maxsize=h.maxsize):
        yield Sample(
            description=sample.description,
            offset=sample.offset,
            size=sample.size,
            time_offset=sample.time_offset / mdhd.timescale,
        )


_DT_1904 = datetime.datetime.utcfromtimestamp(0).replace(year=1904)


def to_datetime(seconds_since_1904: int) -> datetime.datetime:
    """
    Convert seconds since midnight, Jan. 1, 1904, in UTC time
    """
    return _DT_1904 + datetime.timedelta(seconds=seconds_since_1904)
