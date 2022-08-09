import datetime
import sys, os
from mapillary_tools import utils, types
from mapillary_tools.geotag import utils as geotag_utils, camm_parser

if __name__ == "__main__":

    def _convert(path: str):
        delta_points = camm_parser.parse_gpx(path)
        points = [
            types.GPXPoint(
                time=datetime.datetime.utcfromtimestamp(p.time),
                lat=p.lat,
                lon=p.lon,
                alt=p.alt,
            )
            for p in delta_points
        ]
        gpx = geotag_utils.convert_points_to_gpx(points)
        print(gpx.to_xml())

    for path in sys.argv[1:]:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                _convert(p)
        else:
            _convert(path)
