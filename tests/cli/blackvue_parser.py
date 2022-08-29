import os
import pathlib
import sys

from mapillary_tools import utils
from mapillary_tools.geotag import blackvue_parser, utils as geotag_utils


def _convert(path: pathlib.Path):
    points = blackvue_parser.parse_gps_points(path)
    gpx = geotag_utils.convert_points_to_gpx(points)
    model = blackvue_parser.find_camera_model(path)
    gpx.description = f"Extracted from {model}"
    print(gpx.to_xml())


def main():
    for path in sys.argv[1:]:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                _convert(pathlib.Path(p))
        else:
            _convert(pathlib.Path(path))


if __name__ == "__main__":
    main()
