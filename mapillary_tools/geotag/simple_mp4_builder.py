import dataclasses
import typing as T

import construct as C

from .simple_mp4_parser import (
    ChunkLargeOffsetBox,
    ChunkOffsetBox,
    MediaHeaderBox,
    RawSample,
    SampleDescriptionBox,
    SampleSizeBox,
    SampleToChunkBox,
    TimeToSampleBox,
    TrackHeaderBox,
)

UINT32_MAX = 2**32 - 1


Box: C.Struct

LazyBox = C.LazyBound(lambda: C.GreedyRange(Box))

# The struct is for building only.
# For parsing we should use the utils provided in simple_mp4_parser.
# Because it does not handle the extended size,
# although normally a moov struct won't have an extended size.
Box = C.Prefixed(
    C.Int32ub,
    C.Struct(
        "type" / C.Bytes(4),
        "data"
        / C.Switch(
            C.this.type,
            {
                b"moov": LazyBox,
                b"trak": LazyBox,
                b"tkhd": TrackHeaderBox,
                b"stbl": LazyBox,
                b"mdia": LazyBox,
                b"mdhd": MediaHeaderBox,
                # TODO: b"hdlr": MediaHeaderBox,
                b"minf": LazyBox,
                b"stsc": SampleToChunkBox,
                b"stts": TimeToSampleBox,
                b"co64": ChunkLargeOffsetBox,
                b"stco": ChunkOffsetBox,
                b"stsd": SampleDescriptionBox,
                b"stsz": SampleSizeBox,
            },
            C.GreedyBytes,
        ),
    ),
    includelength=True,
)

MP4 = C.GreedyRange(Box)


class BoxDict(T.TypedDict, total=False):
    type: bytes
    data: T.Union[T.List, T.Dict[str, T.Any]]


def _build_stsd(descriptions: T.Sequence[T.Any]) -> BoxDict:
    return {
        "type": b"stsd",
        "data": {
            "entries": descriptions,
        },
    }


def _build_stsz(sizes: T.Sequence[int]) -> BoxDict:
    same_size = all(sz == sizes[0] for sz in sizes)
    if sizes and same_size:
        data = {
            "sample_size": sizes[0],
            "sample_count": len(sizes),
            "entries": [],
        }
    else:
        data = {
            "sample_size": 0,
            "sample_count": len(sizes),
            "entries": sizes,
        }

    return {
        "type": b"stsz",
        "data": data,
    }


@dataclasses.dataclass
class _SampleChunk:
    __slots__ = ("samples_per_chunk", "sample_description_index", "offset")
    samples_per_chunk: int
    sample_description_index: int
    offset: int


def _build_chunks(raw_samples: T.Iterable[RawSample]) -> T.List[_SampleChunk]:
    chunks: T.List[_SampleChunk] = []
    prev_raw_sample = None

    for raw_sample in raw_samples:
        if (
            # if it has the sampe description index as the previous sample
            (
                chunks
                and raw_sample.description_idx == chunks[-1].sample_description_index
            )
            # if it is next to the previous sample (contiguous)
            and (
                prev_raw_sample
                and raw_sample.offset == prev_raw_sample.offset + prev_raw_sample.size
            )
        ):
            # add this sample to the current chunk
            chunks[-1].samples_per_chunk += 1
        else:
            chunks.append(
                _SampleChunk(1, raw_sample.description_idx, raw_sample.offset)
            )

        prev_raw_sample = raw_sample

    return chunks


def _build_stsc(raw_samples: T.Iterable[RawSample]) -> BoxDict:
    chunks = _build_chunks(raw_samples)
    return {
        "type": b"stsc",
        "data": {
            "entries": [
                {
                    "first_chunk": idx + 1,
                    "samples_per_chunk": chunk.samples_per_chunk,
                    "sample_description_index": chunk.sample_description_index,
                }
                for idx, chunk in enumerate(chunks)
            ],
        },
    }


@dataclasses.dataclass
class _CompressedSampleDelta:
    __slots__ = ("sample_count", "sample_delta")
    # make sure dataclasses.asdict() produce the result as SampleSizeBox expects
    sample_count: int
    sample_delta: int


def _build_stts(sample_deltas: T.Iterable[int]) -> BoxDict:
    # compress deltas
    compressed: T.List[_CompressedSampleDelta] = []
    for delta in sample_deltas:
        if compressed and delta == compressed[-1].sample_delta:
            compressed[-1].sample_count += 1
        else:
            compressed.append(_CompressedSampleDelta(1, delta))

    return {
        "type": b"stts",
        "data": {
            "entries": [dataclasses.asdict(td) for td in compressed],
        },
    }


def _build_stco_or_co64(raw_samples: T.Iterable[RawSample]) -> BoxDict:
    chunks = _build_chunks(raw_samples)
    chunk_offsets = [chunk.offset for chunk in chunks]
    is_co64 = any(UINT32_MAX < offset for offset in chunk_offsets)
    return {
        "type": b"co64" if is_co64 else b"stco",
        "data": {
            "entries": chunk_offsets,
        },
    }


def build_stbl_from_raw_samples(
    descriptions: T.Sequence[T.Any], raw_samples: T.Iterable[RawSample]
) -> BoxDict:
    # raw_samples could be iterator so convert to list
    raw_samples = list(raw_samples)
    return {
        "type": b"stbl",
        "data": [
            _build_stsd(descriptions),
            _build_stsz([s.size for s in raw_samples]),
            _build_stco_or_co64(raw_samples),
            _build_stts((s.timedelta for s in raw_samples)),
            _build_stsc(raw_samples),
        ],
    }
