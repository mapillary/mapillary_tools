import dataclasses
import io
import typing as T

from . import (
    construct_mp4_parser as cparser,
    io_utils,
    mp4_sample_parser as sample_parser,
    simple_mp4_parser as parser,
)
from .construct_mp4_parser import BoxDict
from .mp4_sample_parser import RawSample

UINT32_MAX = 2**32 - 1
UINT64_MAX = 2**64 - 1


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


def _build_stss(raw_samples: T.Iterable[RawSample]) -> BoxDict:
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


def _find_box_at_pathx(
    box: T.Union[T.Iterable[BoxDict], BoxDict], path: T.Sequence[bytes]
) -> BoxDict:
    if not path:
        raise ValueError(f"box at path {path} not found")
    boxes: T.Iterable[BoxDict]
    if isinstance(box, dict):
        boxes = [T.cast(BoxDict, box)]
    else:
        boxes = box
    for box in boxes:
        if box["type"] == path[0]:
            if len(path) == 1:
                return box
            else:
                return _find_box_at_pathx(
                    T.cast(T.Iterable[BoxDict], box["data"]), path[1:]
                )
    raise ValueError(f"box at path {path} not found")


def _filter_trak_boxes(
    boxes: T.Iterable[BoxDict],
) -> T.Generator[BoxDict, None, None]:
    for box in boxes:
        if box["type"] == b"trak":
            yield box


def _is_video_trak(box: BoxDict) -> bool:
    hdlr = _find_box_at_pathx(box, [b"trak", b"mdia", b"hdlr"])
    return T.cast(T.Dict[str, T.Any], hdlr["data"])["handler_type"] == b"vide"


def _update_all_trak_tkhd(moov_chilren: T.Sequence[BoxDict]) -> None:
    # an integer that uniquely identifies this track over the entire life-time of this presentation.
    # Track IDs are never re-used and cannot be zero.
    track_id = 1

    for box in _filter_trak_boxes(moov_chilren):
        tkhd = _find_box_at_pathx(box, [b"trak", b"tkhd"])
        d = T.cast(T.Dict[str, T.Any], tkhd["data"])
        d["track_id"] = track_id
        track_id += 1

    mvhd = _find_box_at_pathx(moov_chilren, [b"mvhd"])
    T.cast(T.Dict[str, T.Any], mvhd["data"])["next_track_ID"] = track_id


_STBLChildrenBuilderConstruct = cparser.Box32ConstructBuilder(
    T.cast(cparser.SwitchMapType, cparser.CMAP[b"stbl"])
)


def _update_sbtl(trak: BoxDict, sample_offset: int) -> int:
    assert trak["type"] == b"trak"
    new_samples = []
    for sample in iterate_samples([trak]):
        new_samples.append(
            sample_parser.RawSample(
                description_idx=sample.description_idx,
                offset=sample_offset,
                size=sample.size,
                timedelta=sample.timedelta,
                is_sync=sample.is_sync,
            )
        )
        sample_offset += sample.size
    stbl_box = _find_box_at_pathx(trak, [b"trak", b"mdia", b"minf", b"stbl"])
    descriptions, _ = sample_parser.parse_raw_samples_from_stbl(
        io.BytesIO(T.cast(bytes, stbl_box["data"]))
    )
    stbl_children_boxes = build_stbl_from_raw_samples(descriptions, new_samples)
    new_stbl_bytes = _STBLChildrenBuilderConstruct.build_boxlist(stbl_children_boxes)
    stbl_box["data"] = new_stbl_bytes

    return sample_offset


def iterate_samples(
    moov_children: T.Iterable[BoxDict],
) -> T.Generator[sample_parser.RawSample, None, None]:
    for box in moov_children:
        if box["type"] == b"trak":
            stbl_box = _find_box_at_pathx(box, [b"trak", b"mdia", b"minf", b"stbl"])
            _, raw_samples_iter = sample_parser.parse_raw_samples_from_stbl(
                io.BytesIO(T.cast(bytes, stbl_box["data"]))
            )
            yield from raw_samples_iter


def _build_mdat_header_bytes(mdat_size: int) -> bytes:
    if UINT32_MAX < mdat_size + 8:
        return cparser.BoxHeader64.build(
            {
                "size": mdat_size + 16,
                "type": b"mdat",
            }
        )
    else:
        return cparser.BoxHeader32.build(
            {
                "size": mdat_size + 8,
                "type": b"mdat",
            }
        )


def _filter_moov_children_boxes(
    children: T.Iterable[BoxDict],
) -> T.Generator[BoxDict, None, None]:
    for box in children:
        if box["type"] == b"trak":
            if _is_video_trak(box):
                yield box
        elif box["type"] == b"mvhd":
            yield box


def find_movie_timescale(moov_children: T.Sequence[BoxDict]) -> int:
    mvhd = _find_box_at_pathx(moov_children, [b"mvhd"])
    return T.cast(T.Dict, mvhd["data"])["timescale"]


def _build_moov_bytes(moov_children: T.Sequence[BoxDict]) -> bytes:
    return cparser.MP4WithoutSTBLBuilderConstruct.build_box(
        {
            "type": b"moov",
            "data": moov_children,
        }
    )


_MOOVChildrenParserConstruct = cparser.Box64ConstructBuilder(
    T.cast(cparser.SwitchMapType, cparser.MP4_WITHOUT_STBL_CMAP[b"moov"])
)


def transform_mp4(
    src_fp: T.BinaryIO,
    sample_generator: T.Callable[[T.BinaryIO, T.List[BoxDict]], T.Iterator[io.IOBase]],
) -> io_utils.ChainedIO:
    # extract ftyp
    src_fp.seek(0)
    source_ftyp_box_data = parser.parse_mp4_data_firstx(src_fp, [b"ftyp"])
    source_ftyp_data = cparser.MP4WithoutSTBLBuilderConstruct.build_box(
        {"type": b"ftyp", "data": source_ftyp_box_data}
    )

    # extract moov
    src_fp.seek(0)
    src_moov_data = parser.parse_mp4_data_firstx(src_fp, [b"moov"])
    moov_children = _MOOVChildrenParserConstruct.parse_boxlist(src_moov_data)

    # filter tracks in moov
    moov_children = list(_filter_moov_children_boxes(moov_children))

    # extract video samples
    source_samples = list(iterate_samples(moov_children))
    movie_sample_readers = [
        io_utils.SlicedIO(src_fp, sample.offset, sample.size)
        for sample in source_samples
    ]
    sample_readers = list(sample_generator(src_fp, moov_children))

    _update_all_trak_tkhd(moov_children)

    # moov_boxes should be immutable since here
    mdat_body_size = sum(sample.size for sample in iterate_samples(moov_children))
    return io_utils.ChainedIO(
        [
            io.BytesIO(source_ftyp_data),
            io.BytesIO(_rewrite_moov(len(source_ftyp_data), moov_children)),
            io.BytesIO(_build_mdat_header_bytes(mdat_body_size)),
            *movie_sample_readers,
            *sample_readers,
        ]
    )


def _rewrite_moov(moov_offset: int, moov_boxes: T.Sequence[BoxDict]) -> bytes:
    # build moov for calculating moov size
    sample_offset = 0
    for box in _filter_trak_boxes(moov_boxes):
        sample_offset = _update_sbtl(box, sample_offset)
    moov_data = _build_moov_bytes(moov_boxes)
    moov_data_size = len(moov_data)

    # mdat header size
    mdat_body_size = sum(sample.size for sample in iterate_samples(moov_boxes))
    mdat_header = _build_mdat_header_bytes(mdat_body_size)

    # build moov for real
    sample_offset = moov_offset + len(moov_data) + len(mdat_header)
    for box in _filter_trak_boxes(moov_boxes):
        sample_offset = _update_sbtl(box, sample_offset)
    moov_data = _build_moov_bytes(moov_boxes)
    assert len(moov_data) == moov_data_size, f"{len(moov_data)} != {moov_data_size}"

    return moov_data
