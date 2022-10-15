import argparse
import pathlib

import gpxpy
import gpxpy.gpx

from mapillary_tools import utils
from mapillary_tools.geotag import blackvue_parser, utils as geotag_utils


def _convert_to_track(path: pathlib.Path):
    track = gpxpy.gpx.GPXTrack()
    points = blackvue_parser.parse_gps_points(path)
    segment = geotag_utils.convert_points_to_gpx_segment(points)
    track.segments.append(segment)
    with path.open("rb") as fp:
        model = blackvue_parser.extract_camera_model(fp)
    track.description = f"Extracted from {model}"
    track.name = path.name
    return track


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("blackvue_video_path", nargs="+")
    parsed = parser.parse_args()

    gpx = gpxpy.gpx.GPX()
    for p in utils.find_videos([pathlib.Path(p) for p in parsed.blackvue_video_path]):
        gpx.tracks.append(_convert_to_track(p))
    print(gpx.to_xml())


if __name__ == "__main__":
    main()
