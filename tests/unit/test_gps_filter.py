import mapillary_tools.geo as geo
import mapillary_tools.geotag.gps_filter as gps_filter


def test_upper_whisker():
    assert (
        gps_filter.upper_whisker(
            [7, 7, 31, 31, 47, 75, 87, 115, 116, 119, 119, 155, 177]
        )
        == 251
    )
    assert gps_filter.upper_whisker([1, 2]) == 3.5
    assert gps_filter.upper_whisker([1, 2, 3]) == 3 + 1.5 * (3 - 1)


def test_dbscan():
    def _true_decider(p1, p2):
        return True

    assert gps_filter.dbscan([], _true_decider) == {}

    assert gps_filter.dbscan(
        [[geo.Point(time=1, lat=1, lon=1, angle=None, alt=None)]], _true_decider
    ) == {0: [geo.Point(time=1, lat=1, lon=1, angle=None, alt=None)]}

    assert gps_filter.dbscan(
        [
            [geo.Point(time=1, lat=1, lon=1, angle=None, alt=None)],
            [geo.Point(time=2, lat=1, lon=1, angle=None, alt=None)],
        ],
        _true_decider,
    ) == {
        0: [
            geo.Point(time=1, lat=1, lon=1, angle=None, alt=None),
            geo.Point(time=2, lat=1, lon=1, angle=None, alt=None),
        ]
    }

    assert gps_filter.dbscan(
        [
            [geo.Point(time=1, lat=1, lon=1, angle=None, alt=None)],
            [geo.Point(time=2, lat=1, lon=1, angle=None, alt=None)],
        ],
        gps_filter.speed_le(1000),
    ) == {
        0: [
            geo.Point(time=1, lat=1, lon=1, angle=None, alt=None),
            geo.Point(time=2, lat=1, lon=1, angle=None, alt=None),
        ]
    }
