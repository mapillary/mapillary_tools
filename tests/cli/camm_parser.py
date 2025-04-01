import argparse
import dataclasses
import datetime
import json
import pathlib
import typing as T

import gpxpy
import gpxpy.gpx

from mapillary_tools import geo, utils
from mapillary_tools.camm import camm_parser


def _convert_points_to_gpx_segment(
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


def _convert(path: pathlib.Path):
    track = gpxpy.gpx.GPXTrack()

    track.name = str(path)

    with path.open("rb") as fp:
        camm_info = camm_parser.extract_camm_info(fp)

    if camm_info is None:
        track.description = "Invalid CAMM video"
        return track

    points = T.cast(T.List[geo.Point], camm_info.gps or camm_info.mini_gps)
    track.segments.append(_convert_points_to_gpx_segment(points))

    make_model = json.dumps({"make": camm_info.make, "model": camm_info.model})
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
                camm_info = camm_parser.extract_camm_info(fp, telemetry_only=True)

            if camm_info:
                if "accl" in imu_option:
                    print(
                        json.dumps(
                            [dataclasses.asdict(accl) for accl in camm_info.accl or []]
                        )
                    )
                if "gyro" in imu_option:
                    print(
                        json.dumps(
                            [dataclasses.asdict(gyro) for gyro in camm_info.gyro or []]
                        )
                    )
                if "magn" in imu_option:
                    print(
                        json.dumps(
                            [dataclasses.asdict(magn) for magn in camm_info.magn or []]
                        )
                    )
    else:
        gpx = gpxpy.gpx.GPX()
        for path in video_paths:
            gpx.tracks.append(_convert(path))
        print(gpx.to_xml())


if __name__ == "__main__":
    main()
