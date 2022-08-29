import os
import pathlib
import sys

import gpxpy

from mapillary_tools import utils
from mapillary_tools.geotag import blackvue_parser, utils as geotag_utils


def _convert_to_track(path: pathlib.Path):
    track = gpxpy.gpx.GPXTrack()
    points = blackvue_parser.parse_gps_points(path)
    segment = geotag_utils.convert_points_to_gpx_segment(points)
    track.segments.append(segment)
    model = blackvue_parser.find_camera_model(path)
    track.description = f"Extracted from {model}"
    track.name = path.name
    return track


def main():
    gpx = gpxpy.gpx.GPX()
    for path in sys.argv[1:]:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                gpx.tracks.append(_convert_to_track(pathlib.Path(p)))
        else:
            gpx.tracks.append(_convert_to_track(pathlib.Path(path)))
    print(gpx.to_xml())


if __name__ == "__main__":
    main()
