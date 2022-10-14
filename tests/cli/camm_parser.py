import argparse
import json
import os
import pathlib

import gpxpy

from mapillary_tools import utils
from mapillary_tools.geotag import camm_parser, utils as geotag_utils


def _convert(path: pathlib.Path):
    points = camm_parser.parse_gpx(path)
    track = gpxpy.gpx.GPXTrack()
    track.name = path.name
    track.segments.append(geotag_utils.convert_points_to_gpx_segment(points))
    with open(path, "rb") as fp:
        make, model = camm_parser.extract_camera_make_and_model(fp)
    make_model = json.dumps({"make": make, "model": model})
    track.description = f"Extracted from {make_model}"
    return track


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("camm_video_path", nargs="+")
    parsed = parser.parse_args()

    gpx = gpxpy.gpx.GPX()
    for path in parsed.camm_video_path:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                gpx.tracks.append(_convert(pathlib.Path(p)))
        else:
            gpx.tracks.append(_convert(pathlib.Path(path)))
    print(gpx.to_xml())


if __name__ == "__main__":
    main()
