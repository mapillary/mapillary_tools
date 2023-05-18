import dataclasses
import io
import typing as T
from pathlib import Path

from mapillary_tools import geo, types
from mapillary_tools.geotag import (
    camm_builder,
    camm_parser,
    construct_mp4_parser as cparser,
    simple_mp4_builder,
)


def test_filter_points_by_edit_list():
    assert [] == list(camm_parser.filter_points_by_elst([], []))
    points = [
        geo.Point(time=0, lat=0, lon=0, alt=None, angle=None),
        geo.Point(time=0.23, lat=0, lon=0, alt=None, angle=None),
        geo.Point(time=0.29, lat=0, lon=0, alt=None, angle=None),
        geo.Point(time=0.31, lat=0, lon=0, alt=None, angle=None),
    ]
    assert points == list(camm_parser.filter_points_by_elst(points, []))
    assert [dataclasses.replace(p, time=p.time + 4.4) for p in points] == list(
        camm_parser.filter_points_by_elst(points, [(-1, 3), (-1, 4.4)])
    )

    assert [
        geo.Point(time=0.23 + 4.4, lat=0, lon=0, alt=None, angle=None),
        geo.Point(time=0.31 + 4.4, lat=0, lon=0, alt=None, angle=None),
    ] == list(
        camm_parser.filter_points_by_elst(
            points, [(-1, 3), (-1, 4.4), (0.21, 0.04), (0.30, 0.04)]
        )
    )

    assert [
        geo.Point(time=0.29 + 4.4, lat=0, lon=0, alt=None, angle=None),
        geo.Point(time=0.31 + 4.4, lat=0, lon=0, alt=None, angle=None),
    ] == list(camm_parser.filter_points_by_elst(points, [(-1, 4.4), (0.24, 0.3)]))


def build_mp4(metadata: types.VideoMetadata) -> types.VideoMetadata:
    movie_timescale = simple_mp4_builder.UINT32_MAX

    mvhd: cparser.BoxDict = {
        "type": b"mvhd",
        "data": {
            "creation_time": 1,
            "modification_time": 2,
            "timescale": movie_timescale,
            "duration": int(36000 * movie_timescale),
        },
    }

    empty_mp4: T.List[cparser.BoxDict] = [
        {"type": b"ftyp", "data": b"test"},
        {"type": b"moov", "data": [mvhd]},
    ]
    src = cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist(empty_mp4)
    target_fp = simple_mp4_builder.transform_mp4(
        io.BytesIO(src), camm_builder.camm_sample_generator2(metadata)
    )

    points = camm_parser.extract_points(T.cast(T.BinaryIO, target_fp))
    target_fp.seek(0, io.SEEK_SET)
    make, model = camm_parser.extract_camera_make_and_model(
        T.cast(T.BinaryIO, target_fp)
    )
    return types.VideoMetadata(
        Path(""),
        None,
        filetype=types.FileType.CAMM,
        points=points or [],
        make=make,
        model=model,
    )


def approximate(expected, actual):
    points_equal = all(abs(x.time - y.time) < 0.00001 for x, y in zip(expected, actual))
    the_others_equal = all(
        dataclasses.replace(x, time=0) == dataclasses.replace(y, time=0)
        for x, y in zip(expected, actual)
    )
    return points_equal and the_others_equal


def test_build_and_parse():
    points = [
        geo.Point(time=0.1, lat=0.01, lon=0.2, alt=None, angle=None),
        geo.Point(time=0.23, lat=0.001, lon=0.21, alt=None, angle=None),
        geo.Point(time=0.29, lat=0.002, lon=0.203, alt=None, angle=None),
        geo.Point(time=0.31, lat=0.0025, lon=0.2004, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        None,
        filetype=types.FileType.CAMM,
        points=points,
        make="test_make",
        model="   test_model   ",
    )
    x = build_mp4(metadata)
    assert x.make == "test_make"
    assert x.model == "test_model"
    assert approximate(
        [
            geo.Point(
                time=0.09999999988358467, lat=0.01, lon=0.2, alt=-1.0, angle=None
            ),
            geo.Point(
                time=0.22999999580209396, lat=0.001, lon=0.21, alt=-1.0, angle=None
            ),
            geo.Point(
                time=0.2899999996391125, lat=0.002, lon=0.203, alt=-1.0, angle=None
            ),
            geo.Point(
                time=0.3099999994295649, lat=0.0025, lon=0.2004, alt=-1.0, angle=None
            ),
        ],
        x.points,
    )


def test_build_and_parse2():
    points = [
        geo.Point(time=0.1, lat=0.01, lon=0.2, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        None,
        filetype=types.FileType.CAMM,
        points=points,
        make="test_make汉字",
        model="test_model汉字",
    )
    x = build_mp4(metadata)
    assert x.make == "test_make汉字"
    assert x.model == "test_model汉字"
    assert approximate(
        [geo.Point(time=0.09999999988358468, lat=0.01, lon=0.2, alt=-1.0, angle=None)],
        x.points,
    )


def test_build_and_parse9():
    points = [
        geo.Point(time=0.0, lat=0.01, lon=0.2, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        None,
        filetype=types.FileType.CAMM,
        points=points,
        make="test_make汉字",
        model="test_model汉字",
    )
    x = build_mp4(metadata)
    assert [geo.Point(time=0.0, lat=0.01, lon=0.2, alt=-1.0, angle=None)] == x.points


def test_build_and_parse10():
    points = [
        geo.Point(time=0.0, lat=0.01, lon=0.2, alt=None, angle=None),
        geo.Point(time=0.1, lat=0.03, lon=0.2, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        None,
        filetype=types.FileType.CAMM,
        points=points,
        make="test_make汉字",
        model="test_model汉字",
    )
    x = build_mp4(metadata)
    assert approximate(
        [
            geo.Point(time=0.0, lat=0.01, lon=0.2, alt=-1.0, angle=None),
            geo.Point(time=0.1, lat=0.03, lon=0.2, alt=-1.0, angle=None),
        ],
        x.points,
    )


def test_build_and_parse3():
    points = []
    metadata = types.VideoMetadata(
        Path(""),
        None,
        filetype=types.FileType.CAMM,
        points=points,
        make="test_make汉字",
        model="test_model汉字",
    )
    x = build_mp4(metadata)
    assert [] == x.points
