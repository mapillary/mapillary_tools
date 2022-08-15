import io

import mapillary_tools.geotag.simple_mp4_builder as builder
import mapillary_tools.geotag.simple_mp4_parser as parser


def test_build_moov():
    simple_mp4 = (
        "tests/integration/mapillary_tools_process_images_provider/data/sample-5s.mp4"
    )
    with open(simple_mp4, "rb") as fp:
        parsed = builder.MP4.parse_stream(fp)
    builder.MP4.build(parsed)


def test_build_stbl():
    samples = [
        builder.RawSample(1, 1, 1, 2),
        builder.RawSample(1, 1, 1, 2),
    ]
    s = builder.build_stbl_from_raw_samples(
        [{"format": b"camm", "data": b""}],
        samples,
    )
    d = builder.Box.build(s)
    found = False
    for h, s in parser.parse_path(io.BytesIO(d), [b"stbl"]):
        ss = s.read(h.maxsize)
        assert d[8:] == ss
        descriptions, parsed_samples = parser.parse_raw_samples_from_stbl(
            io.BytesIO(ss)
        )
        print(descriptions, list(parsed_samples))
        found = True
        break
    assert found


def test_build_empty_stbl():
    samples = []
    s = builder.build_stbl_from_raw_samples(
        [{"format": b"camm", "data": b""}],
        samples,
    )
    d = builder.Box.build(s)
    found = False
    for h, s in parser.parse_path(io.BytesIO(d), [b"stbl"]):
        ss = s.read(h.maxsize)
        assert d[8:] == ss
        descriptions, parsed_samples = parser.parse_raw_samples_from_stbl(
            io.BytesIO(ss)
        )
        x = list(parsed_samples)
        assert not x, x
        found = True
        break
    assert found
