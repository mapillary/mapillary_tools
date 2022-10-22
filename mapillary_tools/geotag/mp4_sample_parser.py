import datetime
import io
import typing as T

from . import construct_mp4_parser as cparser, simple_mp4_parser as parser


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


# TODO: can not inherit RawSample?
class Sample(T.NamedTuple):
    # copied from RawSample

    # 1-based index
    description_idx: int
    # sample offset
    offset: int
    # sample size
    size: int
    # sample_delta read from stts entries,
    # i.e. STTS(n) in the forumula DT(n+1) = DT(n) + STTS(n)
    timedelta: float
    # if it is a sync sample
    is_sync: bool

    # extended fields below

    # accumulated sample_delta,
    # i.e. DT(n) in the forumula DT(n+1) = DT(n) + STTS(n)
    time_offset: T.Union[int, float]
    # reference to the sample description
    description: T.Dict


def extract_raw_samples(
    sizes: T.Sequence[int],
    chunk_entries: T.Sequence[T.Dict],
    chunk_offsets: T.Sequence[int],
    timedeltas: T.Sequence[int],
    syncs: T.Optional[T.Set[int]],
) -> T.Generator[RawSample, None, None]:
    if not sizes:
        return

    if not chunk_entries:
        return

    assert len(sizes) <= len(
        timedeltas
    ), f"got less ({len(timedeltas)}) sample time deltas (stts) than expected ({len(sizes)})"

    sample_idx = 0
    chunk_idx = 0

    # iterate compressed chunks
    for entry_idx, entry in enumerate(chunk_entries):
        if entry_idx + 1 < len(chunk_entries):
            nbr_chunks = (
                chunk_entries[entry_idx + 1]["first_chunk"] - entry["first_chunk"]
            )
        else:
            nbr_chunks = 1

        # iterate chunks
        for _ in range(nbr_chunks):
            sample_offset = chunk_offsets[chunk_idx]
            # iterate samples in this chunk
            for _ in range(entry["samples_per_chunk"]):
                is_sync = syncs is None or (sample_idx + 1) in syncs
                yield RawSample(
                    description_idx=entry["sample_description_index"],
                    offset=sample_offset,
                    size=sizes[sample_idx],
                    timedelta=timedeltas[sample_idx],
                    is_sync=is_sync,
                )
                sample_offset += sizes[sample_idx]
                sample_idx += 1
            chunk_idx += 1

    # below handles the single-entry case:
    # If all the chunks have the same number of samples per chunk
    # and use the same sample description, this table has one entry.

    # iterate chunks
    while sample_idx < len(sizes):
        sample_offset = chunk_offsets[chunk_idx]
        # iterate samples in this chunk
        for _ in range(chunk_entries[-1]["samples_per_chunk"]):
            is_sync = syncs is None or (sample_idx + 1) in syncs
            yield RawSample(
                description_idx=chunk_entries[-1]["sample_description_index"],
                offset=sample_offset,
                size=sizes[sample_idx],
                timedelta=timedeltas[sample_idx],
                is_sync=is_sync,
            )
            sample_offset += sizes[sample_idx]
            sample_idx += 1
        chunk_idx += 1


def _extract_samples(
    raw_samples: T.Iterator[RawSample],
    descriptions: T.List,
    media_timescale: int,
) -> T.Generator[Sample, None, None]:
    acc_delta = 0
    for raw_sample in raw_samples:
        yield Sample(
            description_idx=raw_sample.description_idx,
            offset=raw_sample.offset,
            size=raw_sample.size,
            timedelta=raw_sample.timedelta / media_timescale,
            is_sync=raw_sample.is_sync,
            description=descriptions[raw_sample.description_idx - 1],
            time_offset=acc_delta / media_timescale,
        )
        acc_delta += raw_sample.timedelta


def parse_raw_samples_from_stbl(
    stbl: T.BinaryIO, maxsize: int = -1
) -> T.Tuple[T.List[T.Dict], T.Generator[RawSample, None, None]]:
    descriptions = []
    sizes = []
    chunk_offsets = []
    chunk_entries = []
    timedeltas: T.List[int] = []
    syncs: T.Optional[T.Set[int]] = None

    for h, s in parser.parse_boxes(stbl, maxsize=maxsize, extend_eof=False):
        if h.type == b"stsd":
            box = cparser.SampleDescriptionBox.parse(s.read(h.maxsize))
            descriptions = list(box.entries)
        elif h.type == b"stsz":
            box = cparser.SampleSizeBox.parse(s.read(h.maxsize))
            if box.sample_size == 0:
                sizes = list(box.entries)
            else:
                sizes = [box.sample_size for _ in range(box.sample_count)]
        elif h.type == b"stco":
            box = cparser.ChunkOffsetBox.parse(s.read(h.maxsize))
            chunk_offsets = list(box.entries)
        elif h.type == b"co64":
            box = cparser.ChunkLargeOffsetBox.parse(s.read(h.maxsize))
            chunk_offsets = list(box.entries)
        elif h.type == b"stsc":
            box = cparser.SampleToChunkBox.parse(s.read(h.maxsize))
            chunk_entries = list(box.entries)
        elif h.type == b"stts":
            timedeltas = []
            box = cparser.TimeToSampleBox.parse(s.read(h.maxsize))
            for entry in box.entries:
                for _ in range(entry.sample_count):
                    timedeltas.append(entry.sample_delta)
        elif h.type == b"stss":
            box = cparser.SyncSampleBox.parse(s.read(h.maxsize))
            syncs = set(box.entries)

    # some stbl have less timedeltas than the sample count i.e. len(sizes),
    # in this case append 0's to timedeltas
    while len(timedeltas) < len(sizes):
        timedeltas.append(0)

    raw_samples = extract_raw_samples(
        sizes, chunk_entries, chunk_offsets, timedeltas, syncs
    )
    return descriptions, raw_samples


def parse_descriptions_from_trak(stbl: T.BinaryIO, maxsize: int = -1) -> T.List[T.Dict]:
    data = parser.parse_box_data_first(
        stbl, [b"mdia", b"minf", b"stbl", b"stsd"], maxsize=maxsize
    )
    if data is None:
        return []
    box = cparser.SampleDescriptionBox.parse(data)
    return list(box.entries)


def parse_samples_from_trak(
    trak: T.BinaryIO,
    maxsize: int = -1,
) -> T.Generator[Sample, None, None]:
    trak_start_offset = trak.tell()

    trak.seek(trak_start_offset, io.SEEK_SET)
    mdhd_box = parser.parse_box_data_firstx(trak, [b"mdia", b"mdhd"], maxsize=maxsize)
    mdhd = cparser.MediaHeaderBox.parse(mdhd_box)

    trak.seek(trak_start_offset, io.SEEK_SET)
    h, s = parser.parse_box_path_firstx(
        trak, [b"mdia", b"minf", b"stbl"], maxsize=maxsize
    )
    descriptions, raw_samples = parse_raw_samples_from_stbl(s, maxsize=h.maxsize)

    return _extract_samples(raw_samples, descriptions, mdhd.timescale)


_DT_1904 = datetime.datetime.utcfromtimestamp(0).replace(year=1904)


def to_datetime(seconds_since_1904: int) -> datetime.datetime:
    """
    Convert seconds since midnight, Jan. 1, 1904, in UTC time
    """
    return _DT_1904 + datetime.timedelta(seconds=seconds_since_1904)
