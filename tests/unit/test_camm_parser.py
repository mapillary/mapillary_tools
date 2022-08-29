import dataclasses
import io
import typing as T

from mapillary_tools import geo
from mapillary_tools.geotag import camm_builder, camm_parser, simple_mp4_builder


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


def build_mp4(points: T.List[geo.Point]) -> T.Optional[T.List[geo.Point]]:
    movie_timescale = simple_mp4_builder.UINT32_MAX

    mvhd = {
        "type": b"mvhd",
        "data": {
            "creation_time": 1,
            "modification_time": 2,
            "timescale": movie_timescale,
            "duration": int(36000 * movie_timescale),
        },
    }

    empty_mp4 = [
        {"type": b"ftyp", "data": b"test"},
        {"type": b"moov", "data": [mvhd]},
    ]
    src = simple_mp4_builder.QuickBoxStruct32.BoxList.build(empty_mp4)
    target_fp = io.BytesIO()
    simple_mp4_builder.transform_mp4(
        io.BytesIO(src), target_fp, camm_builder.camm_sample_generator2(points)
    )

    target_fp.seek(0)
    return camm_parser.extract_points(target_fp)


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
    x = build_mp4(points)
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
        x,
    )


def test_build_and_parse2():
    points = [
        geo.Point(time=0.1, lat=0.01, lon=0.2, alt=None, angle=None),
    ]
    x = build_mp4(points)
    assert approximate(
        [geo.Point(time=0.09999999988358468, lat=0.01, lon=0.2, alt=-1.0, angle=None)],
        x,
    )


def test_build_and_parse9():
    points = [
        geo.Point(time=0.0, lat=0.01, lon=0.2, alt=None, angle=None),
    ]
    x = build_mp4(points)
    assert [geo.Point(time=0.0, lat=0.01, lon=0.2, alt=-1.0, angle=None)] == x


def test_build_and_parse10():
    points = [
        geo.Point(time=0.0, lat=0.01, lon=0.2, alt=None, angle=None),
        geo.Point(time=0.1, lat=0.03, lon=0.2, alt=None, angle=None),
    ]
    x = build_mp4(points)
    assert approximate(
        [
            geo.Point(time=0.0, lat=0.01, lon=0.2, alt=-1.0, angle=None),
            geo.Point(time=0.1, lat=0.03, lon=0.2, alt=-1.0, angle=None),
        ],
        x,
    )


def test_build_and_parse3():
    points = []
    x = build_mp4(points)
    assert [] == x
