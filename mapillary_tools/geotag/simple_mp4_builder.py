import sys
import dataclasses
import typing as T

if sys.version_info >= (3, 8):
    from typing import Literal, TypedDict  # pylint: disable=no-name-in-module
else:
    from typing_extensions import Literal, TypedDict

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
    SyncSampleBox,
)

UINT32_MAX = 2**32 - 1


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
    Make a box struct that can parse MP4 boxes with both 32-bit and 64-bit sizes.

    It does not construct boxes. For construction, use BoxBuilder32.Box instead.
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

            self._box = C.Select(BoxHeader32 + BoxData32, BoxHeader64 + BoxData64)

        return self._box


class Box32StructBuilder(Box64StructBuilder):
    """
    Make a box struct that can parse or construct MP4 boxes with 32-bit size only.

    The struct does not handle extended size correctly.
    To parse boxes with extended size, use BoxBuilder64.Box instead.
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
    # TODO: b"hdlr": MediaHeaderBox,
    b"stsc": SampleToChunkBox,
    b"stts": TimeToSampleBox,
    b"co64": ChunkLargeOffsetBox,
    b"stco": ChunkOffsetBox,
    b"stsd": SampleDescriptionBox,
    b"stsz": SampleSizeBox,
    b"stss": SyncSampleBox,
}
_full_lazy_box_types = [
    b"moov",
    b"trak",
    b"stbl",
    b"mdia",
    b"minf",
]

FullBoxStruct32 = Box32StructBuilder(_full_switch_map, _full_lazy_box_types).Box
FullMP4Struct32 = C.GreedyRange(FullBoxStruct32)

FullBoxStruct64 = Box64StructBuilder(_full_switch_map, _full_lazy_box_types).Box
FullMP4Struct64 = C.GreedyRange(FullBoxStruct64)

_quick_switch_map = {
    b"tkhd": TrackHeaderBox,
    b"mdhd": MediaHeaderBox,
    # TODO: b"hdlr": MediaHeaderBox,
}

_quick_lazy_box_types = [
    b"moov",
    b"trak",
    b"mdia",
    b"minf",
]

QuickBoxStruct32 = Box32StructBuilder(_quick_switch_map, _quick_lazy_box_types).Box
QuickMP4Struct32 = C.GreedyRange(QuickBoxStruct32)

QuickBoxStruct64 = Box64StructBuilder(_quick_switch_map, _quick_lazy_box_types).Box
QuickMP4Struct64 = C.GreedyRange(QuickBoxStruct64)


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
    boxes = [
        _build_stsd(descriptions),
        _build_stsz([s.size for s in raw_samples]),
        _build_stco_or_co64(raw_samples),
        _build_stts((s.timedelta for s in raw_samples)),
        _build_stsc(raw_samples),
    ]
    if any(not s.is_sync for s in raw_samples):
        boxes.append(_build_stss(raw_samples))
    return boxes
