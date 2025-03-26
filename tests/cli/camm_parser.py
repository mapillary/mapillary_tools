import argparse
import dataclasses
import json
import pathlib
import datetime
import typing as T

import gpxpy
import gpxpy.gpx

from mapillary_tools import telemetry, utils, geo
from mapillary_tools.camm import camm_parser
from mapillary_tools.geotag import utils as geotag_utils


def convert_points_to_gpx_segment(
    points: T.Sequence[geo.Point],
) -> gpxpy.gpx.GPXTrackSegment:
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    for point in points:
        gpx_segment.points.append(
            gpxpy.gpx.GPXTrackPoint(
                point.lat,
                point.lon,
                elevation=point.alt,
                time=datetime.datetime.fromtimestamp(point.time, datetime.timezone.utc),
            )
        )
    return gpx_segment


def _parse_gpx(path: pathlib.Path):
    with path.open("rb") as fp:
        return camm_parser.extract_camm_info(fp)


def _convert(path: pathlib.Path):
    info = _parse_gpx(path)
    if info is None:
        raise RuntimeError(f"Invalid CAMM video {path}")

    points = info.mini_gps or info.gps

    track = gpxpy.gpx.GPXTrack()
    track.name = path.name
    track.segments.append(geotag_utils.convert_points_to_gpx_segment(points))
    with open(path, "rb") as fp:
        make, model = camm_parser.extract_camera_make_and_model(fp)
    make_model = json.dumps({"make": make, "model": model})
    track.description = f"Extracted from {make_model}"
    return track


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--imu", help="Print IMU in JSON")
    parser.add_argument("camm_video_path", nargs="+")
    return parser.parse_args()


def main():
    parsed_args = _parse_args()

    video_paths = utils.find_videos(
        [pathlib.Path(p) for p in parsed_args.camm_video_path]
    )

    if parsed_args.imu:
        imu_option = parsed_args.imu.split(",")

        for path in video_paths:
            with path.open("rb") as fp:
                info = camm_parser.extract_camm_info(fp)

            accls = []
            gyros = []
            magns = []
            if info:
                for m in info:
                    if isinstance(m, telemetry.AccelerationData):
                        accls.append(m)
                    elif isinstance(m, telemetry.GyroscopeData):
                        gyros.append(m)
                    elif isinstance(m, telemetry.MagnetometerData):
                        magns.append(m)

            if "accl" in imu_option:
                print(json.dumps([dataclasses.asdict(accl) for accl in accls]))
            if "gyro" in imu_option:
                print(json.dumps([dataclasses.asdict(gyro) for gyro in gyros]))
            if "magn" in imu_option:
                print(json.dumps([dataclasses.asdict(magn) for magn in magns]))
    else:
        gpx = gpxpy.gpx.GPX()
        for path in video_paths:
            gpx.tracks.append(_convert(path))
        print(gpx.to_xml())


if __name__ == "__main__":
    main()
