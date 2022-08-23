import pathlib
import os, sys

from mapillary_tools import utils
from mapillary_tools.geotag import camm_parser, utils as geotag_utils

if __name__ == "__main__":

    def _convert(path: pathlib.Path):
        points = camm_parser.parse_gpx(path)
        gpx = geotag_utils.convert_points_to_gpx(points)
        print(gpx.to_xml())

    for path in sys.argv[1:]:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                _convert(pathlib.Path(p))
        else:
            _convert(pathlib.Path(path))
