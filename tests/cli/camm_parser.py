import argparse
import dataclasses
import json
import pathlib

import gpxpy
import gpxpy.gpx

from mapillary_tools import telemetry, utils
from mapillary_tools.camm import camm_parser
from mapillary_tools.geotag import utils as geotag_utils


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
                telemetry_measurements = camm_parser.extract_telemetry_data(fp)

            accls = []
            gyros = []
            magns = []
            if telemetry_measurements:
                for m in telemetry_measurements:
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
