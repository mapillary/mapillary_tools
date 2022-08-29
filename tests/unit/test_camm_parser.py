import dataclasses

from mapillary_tools import geo

from mapillary_tools.geotag import camm_parser


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
