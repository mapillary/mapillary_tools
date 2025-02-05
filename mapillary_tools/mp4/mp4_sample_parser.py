import datetime
import typing as T
from pathlib import Path

from . import construct_mp4_parser as cparser, simple_mp4_parser as sparser


class RawSample(T.NamedTuple):
    # 1-based index
    description_idx: int

    # sample offset (offset from the beginning of the file)
    offset: int

    # sample size (in bytes)
    size: int

    # sample_delta read from stts entries that decides when to decode the sample,
    # i.e. STTS(n) in the forumula DT(n+1) = DT(n) + STTS(n)
    # NOTE: timescale is not applied yet (hence int)
    timedelta: int

    # sample composition offset that decides when to present the sample,
    # i.e. CTTS(n) in the forumula CT(n) = DT(n) + CTTS(n).
    # NOTE: timescale is not applied yet (hence int)
    composition_offset: int

    # if it is a sync sample
    is_sync: bool


class Sample(T.NamedTuple):
    raw_sample: RawSample

    # accumulated timedelta in seconds, i.e. DT(n) / timescale
    exact_time: float

    # accumulated composition timedelta in seconds, i.e. CT(n) / timescale
    exact_composition_time: float

    # exact timedelta in seconds, i.e. STTS(n) / timescale
    exact_timedelta: float

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

    assert len(sizes) <= len(timedeltas), (
        f"got less ({len(timedeltas)}) sample time deltas (stts) than expected ({len(sizes)})"
    )

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
    timescale: int,
) -> T.Generator[Sample, None, None]:
    acc_delta = 0
    for raw_sample in raw_samples:
        yield Sample(
            raw_sample=raw_sample,
            description=descriptions[raw_sample.description_idx - 1],
            exact_time=acc_delta / timescale,
            exact_timedelta=raw_sample.timedelta / timescale,
            # CT(n) = DT(n) + CTTS(n)
            exact_composition_time=(acc_delta + raw_sample.composition_offset)
            / timescale,
        )
        acc_delta += raw_sample.timedelta


STBLBoxlistConstruct = cparser.Box64ConstructBuilder(
    T.cast(cparser.SwitchMapType, cparser.CMAP[b"stbl"])
).BoxList


def extract_raw_samples_from_stbl_data(
    stbl: bytes,
) -> T.Tuple[T.List[T.Dict], T.Generator[RawSample, None, None]]:
    descriptions = []
    sizes = []
    chunk_offsets = []
    chunk_entries = []
    timedeltas: T.List[int] = []
    composition_offsets: T.Optional[T.List[int]] = None
    syncs: T.Optional[T.Set[int]] = None

    stbl_children = T.cast(
        T.Sequence[cparser.BoxDict], STBLBoxlistConstruct.parse(stbl)
    )

    for box in stbl_children:
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


_STSDBoxListConstruct = cparser.Box64ConstructBuilder(
    # pyre-ignore[6]: pyre does not support recursive type SwitchMapType
    {b"stsd": cparser.CMAP[b"stsd"]}
).BoxList


class TrackBoxParser:
    trak_children: T.Sequence[cparser.BoxDict]
    stbl_data: bytes

    def __init__(self, trak_children: T.Sequence[cparser.BoxDict]):
        self.trak_children = trak_children
        stbl = cparser.find_box_at_pathx(
            self.trak_children, [b"mdia", b"minf", b"stbl"]
        )
        self.stbl_data = T.cast(bytes, stbl["data"])

    def extract_tkhd_boxdata(self) -> T.Dict:
        return T.cast(
            T.Dict, cparser.find_box_at_pathx(self.trak_children, [b"tkhd"])["data"]
        )

    def is_video_track(self) -> bool:
        hdlr = cparser.find_box_at_pathx(self.trak_children, [b"mdia", b"hdlr"])
        return T.cast(T.Dict[str, T.Any], hdlr["data"])["handler_type"] == b"vide"

    def extract_sample_descriptions(self) -> T.List[T.Dict]:
        # TODO: return [] if parsing fail
        boxes = _STSDBoxListConstruct.parse(self.stbl_data)
        stsd = cparser.find_box_at_pathx(
            T.cast(T.Sequence[cparser.BoxDict], boxes), [b"stsd"]
        )
        return T.cast(T.List[T.Dict], T.cast(T.Dict, stsd["data"])["entries"])

    def extract_elst_boxdata(self) -> T.Optional[T.Dict]:
        box = cparser.find_box_at_path(self.trak_children, [b"edts", b"elst"])
        if box is None:
            return None
        return T.cast(T.Dict, box["data"])

    def extract_mdhd_boxdata(self) -> T.Dict:
        box = cparser.find_box_at_pathx(self.trak_children, [b"mdia", b"mdhd"])
        return T.cast(T.Dict, box["data"])

    def extract_raw_samples(self) -> T.Generator[RawSample, None, None]:
        _, raw_samples = extract_raw_samples_from_stbl_data(self.stbl_data)
        yield from raw_samples

    def extract_samples(self) -> T.Generator[Sample, None, None]:
        descriptions, raw_samples = extract_raw_samples_from_stbl_data(self.stbl_data)
        mdhd = T.cast(
            T.Dict,
            cparser.find_box_at_pathx(self.trak_children, [b"mdia", b"mdhd"])["data"],
        )
        yield from _extract_samples(raw_samples, descriptions, mdhd["timescale"])


class MovieBoxParser:
    moov_children: T.Sequence[cparser.BoxDict]

    def __init__(self, moov_data: bytes):
        self.moov_children = T.cast(
            T.Sequence[cparser.BoxDict],
            cparser.MOOVWithoutSTBLBuilderConstruct.BoxList.parse(moov_data),
        )

    @classmethod
    def parse_file(cls, video_path: Path) -> "MovieBoxParser":
        with video_path.open("rb") as fp:
            moov = sparser.parse_box_data_firstx(fp, [b"moov"])
        return MovieBoxParser(moov)

    @classmethod
    def parse_stream(cls, stream: T.BinaryIO) -> "MovieBoxParser":
        moov = sparser.parse_box_data_firstx(stream, [b"moov"])
        return MovieBoxParser(moov)

    def extract_mvhd_boxdata(self) -> T.Dict:
        mvhd = cparser.find_box_at_pathx(self.moov_children, [b"mvhd"])
        return T.cast(T.Dict, mvhd["data"])

    def extract_tracks(self) -> T.Generator[TrackBoxParser, None, None]:
        for box in self.moov_children:
            if box["type"] == b"trak":
                yield TrackBoxParser(T.cast(T.Sequence[cparser.BoxDict], box["data"]))

    def extract_track_at(self, stream_idx: int) -> TrackBoxParser:
        """
        stream_idx should be the stream_index specifier. See http://ffmpeg.org/ffmpeg.html#Stream-specifiers-1
        > Stream numbering is based on the order of the streams as detected by libavformat
        """
        trak_boxes = [box for box in self.moov_children if box["type"] == b"trak"]
        if not (0 <= stream_idx < len(trak_boxes)):
            raise IndexError(
                "unable to read stream at %d from the track list (length %d)",
                stream_idx,
                len(trak_boxes),
            )
        trak_children = T.cast(
            T.Sequence[cparser.BoxDict], trak_boxes[stream_idx]["data"]
        )
        return TrackBoxParser(trak_children)


_DT_1904 = datetime.datetime.utcfromtimestamp(0).replace(year=1904)


def to_datetime(seconds_since_1904: int) -> datetime.datetime:
    """
    Convert seconds since midnight, Jan. 1, 1904, in UTC time
    """
    return _DT_1904 + datetime.timedelta(seconds=seconds_since_1904)
