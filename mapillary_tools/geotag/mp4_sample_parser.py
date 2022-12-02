import datetime
import io
import typing as T
from pathlib import Path

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
    # sample composition offset,
    # i.e. CTTS(n) in the forumula CT(n) = DT(n) + CTTS(n).
    composition_offset: int
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
    # sample delta in seconds read from stts entries,
    # i.e. (STTS(n) / timescale) in the forumula DT(n+1) = DT(n) + STTS(n)
    timedelta: float
    # sample composition offset in seconds,
    # i.e. (CTTS(n) / timescale) in the forumula CT(n) = DT(n) + CTTS(n).
    composition_offset: float
    # if it is a sync sample
    is_sync: bool

    # extended fields below

    # accumulated sample_delta in seconds,
    # i.e. (DT(n) / timescale) in the forumula DT(n+1) = DT(n) + STTS(n)
    time_offset: T.Union[int, float]
    # accumulated composition offset in seconds,
    # i.e. (CT(n) / timescale) in the forumula CT(n) = DT(n) + CTTS(n).
    composition_time_offset: T.Union[int, float]
    # reference to the sample description
    description: T.Dict


def _extract_raw_samples(
    sizes: T.Sequence[int],
    chunk_entries: T.Sequence[T.Dict],
    chunk_offsets: T.Sequence[int],
    timedeltas: T.Sequence[int],
    composition_offsets: T.Optional[T.Sequence[int]],
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
                composition_offset = (
                    composition_offsets[sample_idx]
                    if composition_offsets is not None
                    else 0
                )
                yield RawSample(
                    description_idx=entry["sample_description_index"],
                    offset=sample_offset,
                    size=sizes[sample_idx],
                    timedelta=timedeltas[sample_idx],
                    composition_offset=composition_offset,
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
            composition_offset = (
                composition_offsets[sample_idx]
                if composition_offsets is not None
                else 0
            )
            yield RawSample(
                description_idx=chunk_entries[-1]["sample_description_index"],
                offset=sample_offset,
                size=sizes[sample_idx],
                timedelta=timedeltas[sample_idx],
                composition_offset=composition_offset,
                is_sync=is_sync,
            )
            sample_offset += sizes[sample_idx]
            sample_idx += 1
        chunk_idx += 1


def _extract_samples(
    raw_samples: T.Iterator[RawSample],
    descriptions: T.List,
) -> T.Generator[Sample, None, None]:
    acc_delta = 0
    for raw_sample in raw_samples:
        yield Sample(
            description_idx=raw_sample.description_idx,
            offset=raw_sample.offset,
            size=raw_sample.size,
            timedelta=raw_sample.timedelta,
            composition_offset=raw_sample.composition_offset,
            is_sync=raw_sample.is_sync,
            description=descriptions[raw_sample.description_idx - 1],
            time_offset=acc_delta,
            # CT(n) = DT(n) + CTTS(n)
            composition_time_offset=(acc_delta + raw_sample.composition_offset),
        )
        acc_delta += raw_sample.timedelta


def _apply_timescale(sample: Sample, media_timescale: int) -> Sample:
    return Sample(
        description_idx=sample.description_idx,
        offset=sample.offset,
        size=sample.size,
        timedelta=sample.timedelta / media_timescale,
        composition_offset=sample.composition_offset / media_timescale,
        is_sync=sample.is_sync,
        description=sample.description,
        time_offset=sample.time_offset / media_timescale,
        composition_time_offset=sample.composition_time_offset / media_timescale,
    )


def parse_raw_samples_from_stbl(
    stbl: T.BinaryIO,
    maxsize: int = -1,
) -> T.Tuple[T.List[T.Dict], T.Generator[RawSample, None, None]]:
    """
    DEPRECATED: use parse_raw_samples_from_stbl_bytes instead
    """

    descriptions = []
    sizes = []
    chunk_offsets = []
    chunk_entries = []
    timedeltas: T.List[int] = []
    composition_offsets: T.Optional[T.List[int]] = None
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
        elif h.type == b"ctts":
            composition_offsets = []
            box = cparser.CompositionTimeToSampleBox.parse(s.read(h.maxsize))
            for entry in box.entries:
                for _ in range(entry.sample_count):
                    composition_offsets.append(entry.sample_offset)
        elif h.type == b"stss":
            box = cparser.SyncSampleBox.parse(s.read(h.maxsize))
            syncs = set(box.entries)

    # some stbl have less timedeltas than the sample count i.e. len(sizes),
    # in this case append 0's to timedeltas
    while len(timedeltas) < len(sizes):
        timedeltas.append(0)
    if composition_offsets is not None:
        while len(composition_offsets) < len(sizes):
            composition_offsets.append(0)

    raw_samples = _extract_raw_samples(
        sizes, chunk_entries, chunk_offsets, timedeltas, composition_offsets, syncs
    )
    return descriptions, raw_samples


STBLBoxlistConstruct = cparser.Box64ConstructBuilder(
    T.cast(cparser.SwitchMapType, cparser.CMAP[b"stbl"])
).BoxList


def parse_raw_samples_from_stbl_bytes(
    stbl: bytes,
) -> T.Tuple[T.List[T.Dict], T.Generator[RawSample, None, None]]:
    descriptions = []
    sizes = []
    chunk_offsets = []
    chunk_entries = []
    timedeltas: T.List[int] = []
    composition_offsets: T.Optional[T.List[int]] = None
    syncs: T.Optional[T.Set[int]] = None

    stbl_boxes = T.cast(T.Sequence[cparser.BoxDict], STBLBoxlistConstruct.parse(stbl))

    for box in stbl_boxes:
        data: T.Dict = T.cast(T.Dict, box["data"])

        if box["type"] == b"stsd":
            descriptions = list(data["entries"])
        elif box["type"] == b"stsz":
            if data["sample_size"] == 0:
                sizes = list(data["entries"])
            else:
                sizes = [data["sample_size"] for _ in range(data["sample_count"])]
        elif box["type"] == b"stco":
            chunk_offsets = list(data["entries"])
        elif box["type"] == b"co64":
            chunk_offsets = list(data["entries"])
        elif box["type"] == b"stsc":
            chunk_entries = list(data["entries"])
        elif box["type"] == b"stts":
            timedeltas = []
            for entry in data["entries"]:
                for _ in range(entry["sample_count"]):
                    timedeltas.append(entry["sample_delta"])
        elif box["type"] == b"ctts":
            composition_offsets = []
            for entry in data["entries"]:
                for _ in range(entry["sample_count"]):
                    composition_offsets.append(entry["sample_offset"])
        elif box["type"] == b"stss":
            syncs = set(data["entries"])

    # some stbl have less timedeltas than the sample count i.e. len(sizes),
    # in this case append 0's to timedeltas
    while len(timedeltas) < len(sizes):
        timedeltas.append(0)
    if composition_offsets is not None:
        while len(composition_offsets) < len(sizes):
            composition_offsets.append(0)

    raw_samples = _extract_raw_samples(
        sizes, chunk_entries, chunk_offsets, timedeltas, composition_offsets, syncs
    )
    return descriptions, raw_samples


def parse_descriptions_from_trak(trak: T.BinaryIO, maxsize: int = -1) -> T.List[T.Dict]:
    data = parser.parse_box_data_first(
        trak, [b"mdia", b"minf", b"stbl", b"stsd"], maxsize=maxsize
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
    mdhd = T.cast(T.Dict, cparser.MediaHeaderBox.parse(mdhd_box))

    trak.seek(trak_start_offset, io.SEEK_SET)
    h, s = parser.parse_box_path_firstx(
        trak, [b"mdia", b"minf", b"stbl"], maxsize=maxsize
    )
    descriptions, raw_samples = parse_raw_samples_from_stbl(s, maxsize=h.maxsize)

    yield from (
        _apply_timescale(s, mdhd["timescale"])
        for s in _extract_samples(raw_samples, descriptions)
    )


STSDBoxListConstruct = cparser.Box64ConstructBuilder(
    # pyre-ignore[6]: pyre does not support recursive type SwitchMapType
    {b"stsd": cparser.CMAP[b"stsd"]}
).BoxList


class TrackBoxParser:
    trak_boxes: T.Sequence[cparser.BoxDict]
    stbl_data: bytes

    def __init__(self, trak_boxes: T.Sequence[cparser.BoxDict]):
        self.trak_boxes = trak_boxes
        stbl = cparser.find_box_at_pathx(self.trak_boxes, [b"mdia", b"minf", b"stbl"])
        self.stbl_data = T.cast(bytes, stbl["data"])

    def tkhd(self) -> T.Dict:
        return T.cast(
            T.Dict, cparser.find_box_at_pathx(self.trak_boxes, [b"tkhd"])["data"]
        )

    def is_video_track(self) -> bool:
        hdlr = cparser.find_box_at_pathx(self.trak_boxes, [b"mdia", b"hdlr"])
        return T.cast(T.Dict[str, T.Any], hdlr["data"])["handler_type"] == b"vide"

    def parse_sample_description(self) -> T.Dict:
        boxes = STSDBoxListConstruct.parse(self.stbl_data)
        stsd = cparser.find_box_at_pathx(
            T.cast(T.Sequence[cparser.BoxDict], boxes), [b"stsd"]
        )
        return T.cast(T.Dict, stsd["data"])

    def parse_raw_samples(self) -> T.Generator[RawSample, None, None]:
        _, raw_samples = parse_raw_samples_from_stbl_bytes(self.stbl_data)
        yield from raw_samples

    def parse_samples(self) -> T.Generator[Sample, None, None]:
        descriptions, raw_samples = parse_raw_samples_from_stbl_bytes(self.stbl_data)
        mdhd = T.cast(
            T.Dict,
            cparser.find_box_at_pathx(self.trak_boxes, [b"mdia", b"mdhd"])["data"],
        )
        yield from (
            _apply_timescale(s, mdhd["timescale"])
            for s in _extract_samples(raw_samples, descriptions)
        )


class MovieBoxParser:
    moov_boxes: T.Sequence[cparser.BoxDict]

    def __init__(self, moov: bytes):
        self.moov_boxes = T.cast(
            T.Sequence[cparser.BoxDict],
            cparser.MOOVWithoutSTBLBuilderConstruct.BoxList.parse(moov),
        )

    @classmethod
    def parse_file(cls, video_path: Path) -> "MovieBoxParser":
        with video_path.open("rb") as fp:
            moov = parser.parse_box_data_firstx(fp, [b"moov"])
        return MovieBoxParser(moov)

    def mvhd(self):
        mvhd = cparser.find_box_at_pathx(self.moov_boxes, [b"mvhd"])
        return mvhd["data"]

    def parse_tracks(self) -> T.Generator[TrackBoxParser, None, None]:
        for box in self.moov_boxes:
            if box["type"] == b"trak":
                yield TrackBoxParser(T.cast(T.Sequence[cparser.BoxDict], box["data"]))

    def parse_track_at(self, stream_idx: int) -> TrackBoxParser:
        """
        stream_idx should be the stream_index specifier. See http://ffmpeg.org/ffmpeg.html#Stream-specifiers-1
        > Stream numbering is based on the order of the streams as detected by libavformat
        """
        trak_boxes = [box for box in self.moov_boxes if box["type"] == b"trak"]
        if not (0 <= stream_idx < len(trak_boxes)):
            raise IndexError(
                "unable to read stream at %d from the track list (length %d)",
                stream_idx,
                len(trak_boxes),
            )
        return TrackBoxParser(
            T.cast(T.Sequence[cparser.BoxDict], trak_boxes[stream_idx]["data"])
        )


_DT_1904 = datetime.datetime.utcfromtimestamp(0).replace(year=1904)


def to_datetime(seconds_since_1904: int) -> datetime.datetime:
    """
    Convert seconds since midnight, Jan. 1, 1904, in UTC time
    """
    return _DT_1904 + datetime.timedelta(seconds=seconds_since_1904)
