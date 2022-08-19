import io
import typing as T

import mapillary_tools.geotag.simple_mp4_builder as builder
import mapillary_tools.geotag.simple_mp4_parser as parser


def _test_build(b, path):
    with open(path, "rb") as fp:
        parsed = b.parse_stream(fp)
    with open(path, "rb") as fp:
        expected_data = fp.read()
    actual_data = b.build(parsed)
    assert expected_data == actual_data


def test_build_sample_5s():
    simple_mp4 = (
        "tests/integration/mapillary_tools_process_images_provider/data/sample-5s.mp4"
    )
    _test_build(builder.FullBoxStruct32.BoxList, simple_mp4)
    _test_build(builder.QuickBoxStruct32.BoxList, simple_mp4)
    _test_build(builder.FullBoxStruct64.BoxList, simple_mp4)
    _test_build(builder.QuickBoxStruct64.BoxList, simple_mp4)


def test_build_hero():
    hero_mp4 = (
        "tests/integration/mapillary_tools_process_images_provider/gopro_data/hero8.mp4"
    )
    _test_build(builder.FullBoxStruct32.BoxList, hero_mp4)
    _test_build(builder.QuickBoxStruct32.BoxList, hero_mp4)
    _test_build(builder.FullBoxStruct64.BoxList, hero_mp4)
    _test_build(builder.QuickBoxStruct64.BoxList, hero_mp4)


def _build_and_parse_stbl(
    descriptions: T.List[T.Any], expected_samples: T.List[builder.RawSample]
):
    s = builder.build_stbl_from_raw_samples(
        descriptions,
        expected_samples,
    )
    d = builder.FullBoxStruct32.Box.build({"type": b"stbl", "data": s})
    h, s = parser.parse_path_firstx(io.BytesIO(d), [b"stbl"])
    ss = s.read(h.maxsize)
    assert d[8:] == ss
    _, parsed_samples = parser.parse_raw_samples_from_stbl(io.BytesIO(ss))
    assert expected_samples == list(parsed_samples)


def test_build_stbl_happy():
    descriptions = [
        {"format": b"camm", "data": b""},
        {"format": b"gopr", "data": b""},
    ]

    samples = [
        builder.RawSample(
            description_idx=1, offset=1, size=1, timedelta=2, is_sync=True
        ),
        builder.RawSample(
            description_idx=1, offset=2, size=9, timedelta=2, is_sync=False
        ),
    ]
    _build_and_parse_stbl(descriptions, samples)

    samples = [
        builder.RawSample(
            description_idx=1, offset=1, size=1, timedelta=2, is_sync=True
        ),
        builder.RawSample(
            description_idx=1, offset=2, size=2, timedelta=2, is_sync=False
        ),
        # another chunk here due to a 1-byte break
        builder.RawSample(
            description_idx=1, offset=5, size=1, timedelta=2, is_sync=True
        ),
        builder.RawSample(
            description_idx=1, offset=6, size=9, timedelta=2, is_sync=False
        ),
    ]
    _build_and_parse_stbl(descriptions, samples)

    samples = [
        builder.RawSample(
            description_idx=1, offset=1, size=1, timedelta=2, is_sync=False
        ),
        builder.RawSample(
            description_idx=1, offset=2, size=2, timedelta=2, is_sync=True
        ),
        # another chunk here
        builder.RawSample(
            description_idx=2, offset=4, size=1, timedelta=2, is_sync=True
        ),
        # another chunk here
        builder.RawSample(
            description_idx=1, offset=5, size=9, timedelta=2, is_sync=True
        ),
    ]
    _build_and_parse_stbl(descriptions, samples)

    samples = [
        builder.RawSample(
            description_idx=1, offset=1, size=1, timedelta=2, is_sync=True
        ),
    ]
    _build_and_parse_stbl(descriptions, samples)

    samples = []
    _build_and_parse_stbl(descriptions, [])


def test_parse_raw_samples_from_stbl():
    # building a stbl with 4 samples
    # chunk 1
    #     sample 1: offset=1, size=1, timedelta=20, is_sync=True
    #     sample 2: offset=2, size=2, timedelta=30, is_sync=False
    # chunk 2
    #     sample 3: offset=5, size=3, timedelta=30, is_sync=True
    #     sample 4: offset=8, size=3, timedelta=50, is_sync=False
    stbl_bytes = builder.FullBoxStruct32.BoxList.build(
        [
            {
                "type": b"stsd",
                "data": {
                    "entries": [
                        {
                            "format": b"mp4a",
                            "data_reference_index": 1,
                            "data": b"\x00\x00\x00\x00",
                        }
                    ]
                },
            },
            {
                "type": b"stsc",
                "data": {
                    "entries": [
                        {
                            "first_chunk": 1,
                            "samples_per_chunk": 2,
                            "sample_description_index": 1,
                        }
                    ]
                },
            },
            {
                "type": b"stsz",
                "data": {
                    "sample_size": 0,
                    "sample_count": 4,
                    "entries": [1, 2, 3, 3],
                },
            },
            {
                # timedelta
                "type": b"stts",
                "data": {
                    "entries": [
                        {
                            "sample_count": 1,
                            "sample_delta": 20,
                        },
                        {
                            "sample_count": 2,
                            "sample_delta": 30,
                        },
                        {
                            "sample_count": 1,
                            "sample_delta": 50,
                        },
                    ],
                },
            },
            {
                # chunk offsets
                "type": b"stco",
                "data": {
                    "entries": [1, 5],
                },
            },
            {
                # sync sample table
                "type": b"stss",
                "data": {
                    "entries": [1, 3],
                },
            },
        ]
    )
    descs, sample_iter = parser.parse_raw_samples_from_stbl(io.BytesIO(stbl_bytes))
    samples = list(sample_iter)
    assert [
        parser.RawSample(
            description_idx=1, offset=1, size=1, timedelta=20, is_sync=True
        ),
        parser.RawSample(
            description_idx=1, offset=2, size=2, timedelta=30, is_sync=False
        ),
        parser.RawSample(
            description_idx=1, offset=5, size=3, timedelta=30, is_sync=True
        ),
        parser.RawSample(
            description_idx=1, offset=8, size=3, timedelta=50, is_sync=False
        ),
    ] == samples
    d = builder.build_stbl_from_raw_samples(descs, samples)
    assert d[1:] == [
        {
            "data": {
                "entries": [
                    {"sample_count": 1, "sample_delta": 20},
                    {"sample_count": 2, "sample_delta": 30},
                    {"sample_count": 1, "sample_delta": 50},
                ]
            },
            "type": b"stts",
        },
        {
            "data": {
                "entries": [
                    {
                        "first_chunk": 1,
                        "sample_description_index": 1,
                        "samples_per_chunk": 2,
                    },
                    {
                        "first_chunk": 2,
                        "sample_description_index": 1,
                        "samples_per_chunk": 2,
                    },
                ]
            },
            "type": b"stsc",
        },
        {
            "data": {"entries": [1, 2, 3, 3], "sample_count": 4, "sample_size": 0},
            "type": b"stsz",
        },
        {"data": {"entries": [1, 5]}, "type": b"co64"},
        {"data": {"entries": [1, 3]}, "type": b"stss"},
    ]


def test_box_header_0_building():
    data = builder.BoxHeader0.build(
        {
            "type": b"ftyp",
        }
    )
    assert data == b"\x00\x00\x00\x00ftyp"
    p = builder.BoxHeader0.parse(data)
    assert p["size32"] == 0


def test_box_header_32_building():
    data = builder.BoxHeader32.build(
        {
            "size": 123,
            "type": b"ftyp",
        }
    )
    assert data == b"\x00\x00\x00{ftyp"
    p = builder.BoxHeader32.parse(data)
    assert p["size"] == 123


def test_box_header_64_building():
    data = builder.BoxHeader64.build(
        {
            "size": 123,
            "type": b"ftyp",
        }
    )
    assert data == b"\x00\x00\x00\x01ftyp\x00\x00\x00\x00\x00\x00\x00{"
    p = builder.BoxHeader64.parse(data)
    assert p["size"] == 123
    assert p["size32"] == 1
