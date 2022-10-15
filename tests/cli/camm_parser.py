import argparse
import json
import pathlib

import gpxpy
import gpxpy.gpx

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
    for p in utils.find_videos([pathlib.Path(p) for p in parsed.camm_video_path]):
        gpx.tracks.append(_convert(p))
    print(gpx.to_xml())


if __name__ == "__main__":
    main()
