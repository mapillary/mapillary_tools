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
class _CompressedSampleChunk:
    __slots__ = ("samples_per_chunk", "sample_description_index")
    samples_per_chunk: int
    sample_description_index: int


def _build_stsc(
    descriptions: T.Sequence[T.Any], raw_samples: T.Iterable[RawSample]
) -> BoxDict:
    # compress samples by description
    compressed: T.List[_CompressedSampleChunk] = []
    for raw_sample in raw_samples:
        assert (
            1 <= raw_sample.description_idx <= len(descriptions)
        ), f"invalid sample description index {raw_sample.description_idx}: must be 1-based and <= {len(descriptions)}"
        if (
            compressed
            and raw_sample.description_idx == compressed[-1].sample_description_index
        ):
            compressed[-1].samples_per_chunk += 1
        else:
            compressed.append(_CompressedSampleChunk(1, raw_sample.description_idx))

    return {
        "type": b"stsc",
        "data": {
            "entries": [
                {
                    "first_chunk": idx + 1,
                    "samples_per_chunk": entry.samples_per_chunk,
                    "sample_description_index": entry.sample_description_index,
                }
                for idx, entry in enumerate(compressed)
            ],
        },
    }


@dataclasses.dataclass
class _CompressedSampleDelta:
    __slots__ = ("count", "delta")
    count: int
    delta: int


def _build_stts(sample_deltas: T.Iterable[int]) -> BoxDict:
    # compress deltas
    compressed: T.List[_CompressedSampleDelta] = []
    for delta in sample_deltas:
        if compressed and delta == compressed[-1].delta:
            compressed[-1].count += 1
        else:
            compressed.append(_CompressedSampleDelta(1, delta))

    return {
        "type": b"stts",
        "data": {
            "entries": [
                {"sample_count": td.count, "sample_delta": td.delta}
                for td in compressed
            ],
        },
    }


def _build_stco_or_co64(offsets: T.Sequence[int]) -> BoxDict:
    is_co64 = any(UINT32_MAX < offset for offset in offsets)
    return {
        "type": b"co64" if is_co64 else b"stco",
        "data": {
            "entries": offsets,
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
            _build_stco_or_co64([s.offset for s in raw_samples]),
            _build_stts((s.timedelta for s in raw_samples)),
            _build_stsc(descriptions, raw_samples),
        ],
    }
