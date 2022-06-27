import sys

from mapillary_tools.geotag import blackvue_utils
from mapillary_tools.geotag import geotag_from_blackvue

if __name__ == "__main__":
    for path in sys.argv[1:]:
        print(f"checking {path}")
        points = geotag_from_blackvue.get_points_from_bv(path, False)
        points2 = blackvue_utils.parse_gps_points(path)
        print(f"read {len(points), len(points2)} points")
        assert points == points2
