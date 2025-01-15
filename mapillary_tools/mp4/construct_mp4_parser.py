# pyre-ignore-all-errors[5, 16, 21, 58]

import typing as T

import construct as C


BoxType = T.Literal[
    b"@mak",
    b"@mod",
    b"co64",
    b"ctts",
    b"dinf",
    b"dref",
    b"edts",
    b"edts",
    b"elst",
    b"free",
    b"ftyp",
    b"hdlr",
    b"mdhd",
    b"mdia",
    b"minf",
    b"moof",
    b"moov",
    b"mvhd",
    b"stbl",
    b"stco",
    b"stsc",
    b"stsd",
    b"stss",
    b"stsz",
    b"stts",
    b"tkhd",
    b"traf",
    b"trak",
    b"udta",
    b"url ",
    b"urn ",
]


class BoxDict(T.TypedDict, total=True):
    type: BoxType
    data: T.Union[T.Sequence["BoxDict"], T.Dict[str, T.Any], bytes]


_UNITY_MATRIX = [0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000]


# Box Type: ‘mvhd’
# Container: Movie Box (‘moov’)
# Mandatory: Yes
# Quantity: Exactly one
MovieHeaderBox = C.Struct(
    "version" / C.Default(C.Int8ub, 1),
    "flags" / C.Default(C.Int24ub, 0),
    "creation_time" / C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub),
    "modification_time" / C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub),
    "timescale" / C.Int32ub,
    "duration" / C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub),
    "rate" / C.Default(C.Int32sb, 0x00010000),
    "volume" / C.Default(C.Int16sb, 0x0100),
    C.Padding(2),  # const bit(16) reserved = 0;
    C.Padding(8),  # const unsigned int(32)[2] reserved = 0;
    "matrix" / C.Default(C.Int32sb[9], _UNITY_MATRIX),
    C.Padding(24),  # bit(32)[6]  pre_defined = 0;
    "next_track_ID" / C.Default(C.Int32ub, 0xFFFFFFFF),
)

# moov -> trak -> tkhd
TrackHeaderBox = C.Struct(
    "version" / C.Default(C.Int8ub, 1),
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

# Box Type: ‘elst’
# Container: Edit Box (‘edts’)
# Mandatory: No
# Quantity: Zero or one
EditBox = C.Struct(
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    "entries"
    / C.PrefixedArray(
        C.Int32ub,
        C.Struct(
            # in units of the timescale in the Movie Header Box
            "segment_duration"
            / C.IfThenElse(C.this._._.version == 1, C.Int64sb, C.Int32sb),
            # in media time scale units, in composition time
            "media_time" / C.IfThenElse(C.this._._.version == 1, C.Int64sb, C.Int32sb),
            "media_rate_integer" / C.Int16sb,
            "media_rate_fraction" / C.Int16sb,
        ),
    ),
)

# moov -> trak -> mdia -> mdhd
# Box Type: ‘mdhd’
# Container: Media Box (‘mdia’)
# Mandatory: Yes
# Quantity: Exactly one
MediaHeaderBox = C.Struct(
    "version" / C.Default(C.Int8ub, 1),
    "flags" / C.Default(C.Int24ub, 0),
    "creation_time" / C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub),
    "modification_time" / C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub),
    "timescale" / C.Int32ub,
    "duration" / C.IfThenElse(C.this.version == 1, C.Int64ub, C.Int32ub),
    "language" / C.Int16ub,
    C.Padding(2),
)


# moov -> trak -> mdia -> hdlr
# Box Type: ‘hdlr’
# Container: Media Box (‘mdia’) or Meta Box (‘meta’)
# Mandatory: Yes
# Quantity: Exactly one
HandlerReferenceBox = C.Struct(
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    # Tests fail if using C.Padding(4),
    "_pre_defined" / C.Default(C.Int32ub, 0),
    "handler_type" / C.Bytes(4),
    # Tests fail if using C.Padding(3 * 4),
    "_reserved" / C.Default(C.Int32ub[3], [0, 0, 0]),
    "name" / C.GreedyString("utf8"),
)

# BoxTypes: ‘url ‘,‘urn ‘,‘dref’
# Container: Data Information Box (‘dinf’)
# Mandatory: Yes
# Quantity: Exactly one
DataEntryUrlBox = C.Struct(
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    # the data entry contains URL location which should be utf8 string
    # but for compatibility we parse or build it as bytes
    "data" / C.GreedyBytes,
)

DataEntryUrnBox = C.Struct(
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    # the data entry contains URN name and location which should be utf8 string
    # but for compatibility we parse or build it as bytes
    "data" / C.GreedyBytes,
)

DataReferenceEntryBox = C.Prefixed(
    C.Int32ub,
    C.Struct(
        "type" / C.Bytes(4),
        "data"
        / C.Switch(
            C.this.type,
            {b"urn ": DataEntryUrnBox, b"url ": DataEntryUrlBox},
            C.GreedyBytes,
        ),
    ),
    includelength=True,
)

DataReferenceBox = C.Struct(
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    "entries"
    / C.PrefixedArray(
        C.Int32ub,
        DataReferenceEntryBox,
    ),
)

_SampleEntryBox = C.Prefixed(
    C.Int32ub,
    C.Struct(
        "format" / C.Bytes(4),
        C.Padding(6),
        # reference entry in dinf/dref
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
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    "entries" / C.PrefixedArray(C.Int32ub, _SampleEntryBox),
)


# moov -> trak -> mdia -> minf -> stbl -> stsz
# Box Type: ‘stsz’, ‘stz2’
# Container: Sample Table Box (‘stbl’)
# Mandatory: Yes
# Quantity: Exactly one variant must be present
SampleSizeBox = C.Struct(
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
# Container: Sample Table Box (‘stbl’)
# Mandatory: Yes
# Quantity: Exactly one variant must be present
ChunkOffsetBox = C.Struct(
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
# Container: Sample Table Box (‘stbl’)
# Mandatory: Yes
# Quantity: Exactly one
TimeToSampleBox = C.Struct(
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

# moov -> trak -> mdia -> minf -> stbl -> ctts
# Box Type: ‘ctts’
# Container: Sample Table Box (‘stbl’)
# Mandatory: No
# Quantity: Zero or one
CompositionTimeToSampleBox = C.Struct(
    "version" / C.Default(C.Int8ub, 0),
    "flags" / C.Default(C.Int24ub, 0),
    "entries"
    / C.Default(
        C.PrefixedArray(
            C.Int32ub,
            C.Struct(
                "sample_count" / C.Int32ub,
                "sample_offset" / C.Int32ub,
            ),
        ),
        [],
    ),
)

# moov -> trak -> mdia -> minf -> stbl -> stsc
# Box Type: ‘stsc’
# Container: Sample Table Box (‘stbl’)
# Mandatory: Yes
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
# Container: Sample Table Box (‘stbl’)
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


SwitchMapType = T.Dict[BoxType, T.Union[C.Construct, "SwitchMapType"]]


class Box64ConstructBuilder:
    """
    Build a box struct that **parses** MP4 boxes with both 32-bit and 64-bit sizes.

    NOTE: Do not build data with this struct. For building, use Box32StructBuilder instead.
    """

    _box: T.Optional[C.Construct]

    def __init__(
        self,
        nested_switch_map: SwitchMapType,
        extend_eof: bool = False,
    ) -> None:
        self._box = None
        self._extend_eof = extend_eof
        switch_map = {}
        for k, v in nested_switch_map.items():
            if isinstance(v, dict):
                switch_map[k] = self.__class__(v, extend_eof=False).BoxList
            else:
                switch_map[k] = v
        self._switch = C.Switch(
            C.this.type,
            switch_map,
            C.GreedyBytes,
        )

    @property
    def Box(self) -> C.Construct:
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

            if self._extend_eof:
                self._box = C.Select(
                    BoxHeader32 + BoxData32,
                    BoxHeader64 + BoxData64,
                    BoxHeader0 + BoxData0,
                )
            else:
                self._box = C.Select(BoxHeader32 + BoxData32, BoxHeader64 + BoxData64)

        return self._box

    @property
    def BoxList(self) -> C.Construct:
        return C.GreedyRange(self.Box)

    def parse_box(self, data: bytes) -> BoxDict:
        return T.cast(BoxDict, self.Box.parse(data))

    def parse_boxlist(self, data: bytes) -> T.List[BoxDict]:
        return T.cast(T.List[BoxDict], self.BoxList.parse(data))


class Box32ConstructBuilder(Box64ConstructBuilder):
    """
    Build a box struct that parses or builds MP4 boxes with 32-bit size only.

    NOTE: The struct does not handle extended size correctly.
    To parse boxes with extended size, use Box64StructBuilder instead.
    """

    @property
    def Box(self) -> C.Construct:
        if self._box is None:
            self._box = C.Prefixed(
                C.Int32ub,
                C.Struct("type" / C.Bytes(4), "data" / self._switch),
                includelength=True,
            )

        return self._box

    def parse_box(self, data: bytes) -> BoxDict:
        raise NotImplementedError("Box32ConstructBuilder does not support parsing")

    def parse_boxlist(self, data: bytes) -> T.List[BoxDict]:
        raise NotImplementedError("Box32ConstructBuilder does not support parsing")

    def build_box(self, box: BoxDict) -> bytes:
        return self.Box.build(box)

    def build_boxlist(self, boxes: T.Sequence[BoxDict]) -> bytes:
        return self.BoxList.build(boxes)


# pyre-ignore[9]: pyre does not support recursive type SwitchMapType
CMAP: SwitchMapType = {
    b"tkhd": TrackHeaderBox,
    b"mdhd": MediaHeaderBox,
    b"stsc": SampleToChunkBox,
    b"stts": TimeToSampleBox,
    b"ctts": CompositionTimeToSampleBox,
    b"co64": ChunkLargeOffsetBox,
    b"stco": ChunkOffsetBox,
    b"stsd": SampleDescriptionBox,
    b"stsz": SampleSizeBox,
    b"stss": SyncSampleBox,
    b"hdlr": HandlerReferenceBox,
    b"dref": DataReferenceBox,
    b"urn ": DataEntryUrnBox,
    b"url ": DataEntryUrlBox,
    b"mvhd": MovieHeaderBox,
    b"elst": EditBox,
}

# pyre-ignore[6]: pyre does not support recursive type SwitchMapType
CMAP[b"stbl"] = {
    b"stsd": CMAP[b"stsd"],
    b"stts": CMAP[b"stts"],
    b"ctts": CMAP[b"ctts"],
    b"stsc": CMAP[b"stsc"],
    b"stsz": CMAP[b"stsz"],
    b"stco": CMAP[b"stco"],
    b"co64": CMAP[b"co64"],
    b"stss": CMAP[b"stss"],
}

# pyre-ignore[6]: pyre does not support recursive type SwitchMapType
CMAP[b"dinf"] = {
    b"dref": CMAP[b"dref"],
}

# pyre-ignore[6]: pyre does not support recursive type SwitchMapType
CMAP[b"minf"] = {
    b"dinf": CMAP[b"dinf"],
    b"stbl": CMAP[b"stbl"],
}

# pyre-ignore[6]: pyre does not support recursive type SwitchMapType
CMAP[b"mdia"] = {
    b"mdhd": CMAP[b"mdhd"],
    b"hdlr": CMAP[b"hdlr"],
    b"minf": CMAP[b"minf"],
}

# pyre-ignore[6]: pyre does not support recursive type SwitchMapType
CMAP[b"edts"] = {
    b"elst": CMAP[b"elst"],
}

# pyre-ignore[6]: pyre does not support recursive type SwitchMapType
CMAP[b"trak"] = {
    b"tkhd": CMAP[b"tkhd"],
    b"edts": CMAP[b"edts"],
    b"mdia": CMAP[b"mdia"],
}

# pyre-ignore[6]: pyre does not support recursive type SwitchMapType
CMAP[b"moov"] = {
    b"mvhd": CMAP[b"mvhd"],
    b"udta": {},
    b"trak": CMAP[b"trak"],
}

# pyre-ignore[9]: pyre does not support recursive type SwitchMapType
MP4_CMAP: SwitchMapType = {
    b"moov": CMAP[b"moov"],
}


def _new_cmap_without_boxes(
    switch_map: SwitchMapType, box_types: T.Sequence[BoxType]
) -> SwitchMapType:
    new_switch_map = {}
    for k, v in switch_map.items():
        if k in box_types:
            continue
        if isinstance(v, dict):
            new_switch_map[k] = _new_cmap_without_boxes(v, box_types)
        else:
            new_switch_map[k] = v
    return new_switch_map


# pyre-ignore[9]: pyre does not support recursive type SwitchMapType
MP4_WITHOUT_STBL_CMAP: SwitchMapType = {
    # pyre-ignore[6]: pyre does not support recursive type SwitchMapType
    b"moov": _new_cmap_without_boxes(CMAP[b"moov"], [b"stbl"]),
}

# for parsing mp4 only
MP4ParserConstruct = Box64ConstructBuilder(MP4_CMAP, extend_eof=True)
MP4WithoutSTBLParserConstruct = Box64ConstructBuilder(MP4_WITHOUT_STBL_CMAP)

# for building mp4 only
MP4BuilderConstruct = Box32ConstructBuilder(MP4_CMAP, extend_eof=True)
MP4WithoutSTBLBuilderConstruct = Box32ConstructBuilder(MP4_WITHOUT_STBL_CMAP)

MOOVWithoutSTBLBuilderConstruct = Box32ConstructBuilder(
    T.cast(SwitchMapType, MP4_WITHOUT_STBL_CMAP[b"moov"]),
    extend_eof=False,
)


def find_box_at_pathx(
    box: T.Union[T.Sequence[BoxDict], BoxDict], path: T.Sequence[bytes]
) -> BoxDict:
    found = find_box_at_path(box, path)
    if found is None:
        raise ValueError(f"box at path {path} not found")
    return found


def find_box_at_path(
    box: T.Union[T.Sequence[BoxDict], BoxDict], path: T.Sequence[bytes]
) -> T.Optional[BoxDict]:
    if not path:
        return None

    boxes: T.Sequence[BoxDict]
    if isinstance(box, dict):
        boxes = [T.cast(BoxDict, box)]
    else:
        boxes = T.cast(T.Sequence[BoxDict], box)

    for box in boxes:
        if box["type"] == path[0]:
            if len(path) == 1:
                return box
            box_data = T.cast(T.Sequence[BoxDict], box["data"])
            # ListContainer from construct is not sequence
            assert isinstance(box_data, T.Sequence), (
                f"expect a list of boxes but got {type(box_data)} at path {path}"
            )
            found = find_box_at_path(box_data, path[1:])
            if found is not None:
                return found

    return None
