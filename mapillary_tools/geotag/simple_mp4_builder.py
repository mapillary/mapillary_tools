import dataclasses
import sys
import typing as T

if sys.version_info >= (3, 8):
    from typing import Literal, TypedDict  # pylint: disable=no-name-in-module
else:
    from typing_extensions import Literal, TypedDict

import construct as C

from .simple_mp4_parser import (
    ChunkLargeOffsetBox,
    ChunkOffsetBox,
    DataEntryUrlBox,
    DataEntryUrnBox,
    DataReferenceBox,
    HandlerReferenceBox,
    MediaHeaderBox,
    RawSample,
    SampleDescriptionBox,
    SampleSizeBox,
    SampleToChunkBox,
    SyncSampleBox,
    TimeToSampleBox,
    TrackHeaderBox,
)

UINT32_MAX = 2**32 - 1


BoxHeader0 = C.Struct(
    "size32" / C.Const(0, C.Int32ub),
    "type" / C.Bytes(4),
)

BoxHeader32 = C.Struct(
    "size" / C.Int32ub,
    "type" / C.Bytes(4),
)

BoxHeader64 = C.Struct(
    "size32" / C.Const(1, C.Int32ub),
    "type" / C.Bytes(4),
    "size" / C.Int64ub,
)


class Box64StructBuilder:
    """
    Build a box struct that **parses** MP4 boxes with both 32-bit and 64-bit sizes.

    NOTE: Do not build data with this struct. For building, use Box32StructBuilder instead.
    """

    _box: C.Struct

    def __init__(
        self, switch_map: T.Dict[bytes, C.Struct], lazy_box_types: T.Sequence[bytes]
    ) -> None:
        self._box = None
        self._box_type_switch_map = {**switch_map}
        lazy_box = C.LazyBound(lambda: C.GreedyRange(self.Box))
        for box_type in lazy_box_types:
            self._box_type_switch_map[box_type] = lazy_box
        self._switch = C.Switch(
            C.this.type,
            self._box_type_switch_map,
            C.GreedyBytes,
        )

    @property
    def Box(self) -> C.Struct:
        if self._box is None:
            BoxData32 = C.Struct(
                "data"
                / C.FixedSized(
                    C.this.size - 8,
                    self._switch,
                )
            )

            BoxData64 = C.Struct(
                "data"
                / C.FixedSized(
                    C.this.size - 16,
                    self._switch,
                )
            )

            BoxData0 = C.Struct(
                "data" / self._switch,
            )

            self._box = C.Select(
                BoxHeader32 + BoxData32, BoxHeader64 + BoxData64, BoxHeader0 + BoxData0
            )

        return self._box

    @property
    def BoxList(self) -> C.Struct:
        return C.GreedyRange(self.Box)


class Box32StructBuilder(Box64StructBuilder):
    """
    Build a box struct that parses or builds MP4 boxes with 32-bit size only.

    NOTE: The struct does not handle extended size correctly.
    To parse boxes with extended size, use Box64StructBuilder instead.
    """

    @property
    def Box(self) -> C.Struct:
        if self._box is None:
            self._box = C.Prefixed(
                C.Int32ub,
                C.Struct("type" / C.Bytes(4), "data" / self._switch),
                includelength=True,
            )

        return self._box


_full_switch_map = {
    b"tkhd": TrackHeaderBox,
    b"mdhd": MediaHeaderBox,
    b"stsc": SampleToChunkBox,
    b"stts": TimeToSampleBox,
    b"co64": ChunkLargeOffsetBox,
    b"stco": ChunkOffsetBox,
    b"stsd": SampleDescriptionBox,
    b"stsz": SampleSizeBox,
    b"stss": SyncSampleBox,
    b"hdlr": HandlerReferenceBox,
    b"dref": DataReferenceBox,
    b"urn ": DataEntryUrnBox,
    b"url ": DataEntryUrlBox,
}
_full_lazy_box_types = [
    b"moov",
    b"trak",
    b"edts",
    b"mdia",
    b"minf",
    b"stbl",
    b"mvex",
    b"moof",
    b"traf",
    b"mfra",
    b"dinf",
]

FullBoxStruct32 = Box32StructBuilder(_full_switch_map, _full_lazy_box_types)
FullBoxStruct64 = Box64StructBuilder(_full_switch_map, _full_lazy_box_types)

_quick_switch_map = {
    b"tkhd": TrackHeaderBox,
    b"mdhd": MediaHeaderBox,
    b"hdlr": HandlerReferenceBox,
}

_quick_lazy_box_types = [
    b"moov",
    b"trak",
    b"mdia",
    b"minf",
    b"mvex",
]

QuickBoxStruct32 = Box32StructBuilder(_quick_switch_map, _quick_lazy_box_types)
QuickBoxStruct64 = Box64StructBuilder(_quick_switch_map, _quick_lazy_box_types)


class BoxDict(TypedDict, total=False):
    type: bytes
    data: T.Union[T.List, T.Dict[str, T.Any], bytes]


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


def _build_co64(raw_samples: T.Iterable[RawSample]) -> BoxDict:
    chunks = _build_chunks(raw_samples)
    return {
        "type": b"co64",
        "data": {
            "entries": [chunk.offset for chunk in chunks],
        },
    }


def _build_stss(raw_samples: T.Iterable[RawSample]):
    return {
        "type": b"stss",
        "data": {
            "entries": [idx + 1 for idx, s in enumerate(raw_samples) if s.is_sync],
        },
    }


def build_stbl_from_raw_samples(
    descriptions: T.Sequence[T.Any], raw_samples: T.Iterable[RawSample]
) -> T.List[BoxDict]:
    # raw_samples could be iterator so convert to list
    raw_samples = list(raw_samples)
    # It is recommended that the boxes within the Sample Table Box be in the following order:
    # Sample Description, Time to Sample, Sample to Chunk, Sample Size, Chunk Offset.
    boxes = [
        _build_stsd(descriptions),
        _build_stts((s.timedelta for s in raw_samples)),
        _build_stsc(raw_samples),
        _build_stsz([s.size for s in raw_samples]),
        # always build as co64 to make sure moov box size is independent of chunk offsets for the same sample list
        # so we can calculate the moov box size in advance
        _build_co64(raw_samples),
    ]
    if any(not s.is_sync for s in raw_samples):
        boxes.append(_build_stss(raw_samples))
    return boxes
