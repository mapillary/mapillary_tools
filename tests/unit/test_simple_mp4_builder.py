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
    b = builder.FullMP4Struct32
    _test_build(b, simple_mp4)
    b = builder.QuickMP4Struct32
    _test_build(b, simple_mp4)
    b = builder.FullMP4Struct64
    _test_build(b, simple_mp4)
    b = builder.QuickMP4Struct64
    _test_build(b, simple_mp4)


def test_build_hero():
    hero_mp4 = (
        "tests/integration/mapillary_tools_process_images_provider/gopro_data/hero8.mp4"
    )
    b = builder.FullMP4Struct32
    _test_build(b, hero_mp4)
    b = builder.QuickMP4Struct32
    _test_build(b, hero_mp4)
    b = builder.FullMP4Struct64
    _test_build(b, hero_mp4)
    b = builder.QuickMP4Struct64
    _test_build(b, hero_mp4)


def _build_and_parse_stbl(
    descriptions: T.List[T.Any], expected_samples: T.List[builder.RawSample]
):
    s = builder.build_stbl_from_raw_samples(
        descriptions,
        expected_samples,
    )
    d = builder.FullBoxStruct32.build({"type": b"stbl", "data": s})
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
