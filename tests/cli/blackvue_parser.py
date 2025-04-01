from __future__ import annotations

import argparse
import datetime
import pathlib
import typing as T

import gpxpy
import gpxpy.gpx

from mapillary_tools import blackvue_parser, geo, utils


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


def _convert_to_track(path: pathlib.Path):
    track = gpxpy.gpx.GPXTrack()
    track.name = str(path)

    with path.open("rb") as fp:
        blackvue_info = blackvue_parser.extract_blackvue_info(fp)

    if blackvue_info is None:
        track.description = "Invalid BlackVue video"
        return track

    segment = _convert_points_to_gpx_segment(blackvue_info.gps or [])
    track.segments.append(segment)
    with path.open("rb") as fp:
        model = blackvue_parser.extract_camera_model(fp)
    track.description = f"Extracted from {model}"

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
