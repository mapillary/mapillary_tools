import argparse
import datetime
import os
import pathlib
import typing as T

import gpxpy

import mapillary_tools.geotag.gpmf_parser as gpmf_parser
import mapillary_tools.utils as utils


def convert_points_to_gpx(points: T.Sequence[gpmf_parser.Point]) -> gpxpy.gpx.GPXTrack:
    gpx_track = gpxpy.gpx.GPXTrack()
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(gpx_segment)
    gps_fix_map = {
        0: "none",
        2: "2d",
        3: "3d",
    }
    for point in points:
        gpxp = gpxpy.gpx.GPXTrackPoint(
            point.lat,
            point.lon,
            elevation=point.alt,
            time=datetime.datetime.utcfromtimestamp(point.time),
            comment=f"precision: {point.gps_precision}",
        )
        gpxp.type_of_gpx_fix = gps_fix_map.get(point.gps_fix)
        gpx_segment.points.append(gpxp)

    return gpx_track


def _convert(gpx: gpxpy.gpx.GPX, path: pathlib.Path, gps_fix=None, max_precision=None):
    if gps_fix is not None:
        gps_fix = set(int(x) for x in gps_fix.split(","))
    points = gpmf_parser.parse_gpx(path)
    points = [
        p
        for p in points
        if (gps_fix is None or p.gps_fix in gps_fix)
        and (max_precision is None or p.gps_precision <= max_precision)
    ]
    gpx_track = convert_points_to_gpx(points)
    gpx_track.name = path.name
    gpx.tracks.append(gpx_track)


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="+", help="Path to video file or directory")
    parser.add_argument(
        "--max_precision",
        type=int,
        help="Show GPS points under this precision",
    )
    parser.add_argument("--gps_fix", help="Show GPS points with this GPS fix")
    return parser.parse_args()


def main():
    parsed_args = _parse_args()
    gpx = gpxpy.gpx.GPX()

    for path in parsed_args.path:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                _convert(
                    gpx, pathlib.Path(p), parsed_args.gps_fix, parsed_args.max_precision
                )
        else:
            _convert(
                gpx, pathlib.Path(path), parsed_args.gps_fix, parsed_args.max_precision
            )

    print(gpx.to_xml())


if __name__ == "__main__":
    main()
