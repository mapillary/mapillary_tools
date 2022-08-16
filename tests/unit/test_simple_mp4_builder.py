import io
import typing as T

import mapillary_tools.geotag.simple_mp4_builder as builder
import mapillary_tools.geotag.simple_mp4_parser as parser


def test_build_moov():
    simple_mp4 = (
        "tests/integration/mapillary_tools_process_images_provider/data/sample-5s.mp4"
    )
    with open(simple_mp4, "rb") as fp:
        parsed = builder.FullMP464.parse_stream(fp)
    builder.FullMP464.build(parsed)


def _build_and_parse_stbl(
    descriptions: T.List[T.Any], expected_samples: T.List[builder.RawSample]
):
    s = builder.build_stbl_from_raw_samples(
        descriptions,
        expected_samples,
    )
    d = builder.FullBox32.build(s)
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
        builder.RawSample(description_idx=1, offset=1, size=1, timedelta=2),
        builder.RawSample(description_idx=1, offset=2, size=9, timedelta=2),
    ]
    _build_and_parse_stbl(descriptions, samples)

    samples = [
        builder.RawSample(description_idx=1, offset=1, size=1, timedelta=2),
        builder.RawSample(description_idx=1, offset=2, size=2, timedelta=2),
        # another chunk here due to a 1-byte break
        builder.RawSample(description_idx=1, offset=5, size=1, timedelta=2),
        builder.RawSample(description_idx=1, offset=6, size=9, timedelta=2),
    ]
    _build_and_parse_stbl(descriptions, samples)

    samples = [
        builder.RawSample(description_idx=1, offset=1, size=1, timedelta=2),
        builder.RawSample(description_idx=1, offset=2, size=2, timedelta=2),
        # another chunk here
        builder.RawSample(description_idx=2, offset=4, size=1, timedelta=2),
        # another chunk here
        builder.RawSample(description_idx=1, offset=5, size=9, timedelta=2),
    ]
    _build_and_parse_stbl(descriptions, samples)

    samples = [
        builder.RawSample(description_idx=1, offset=1, size=1, timedelta=2),
    ]
    _build_and_parse_stbl(descriptions, samples)

    samples = []
    _build_and_parse_stbl(descriptions, [])
