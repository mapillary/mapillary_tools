import argparse
import datetime
import json
import os
import pathlib
import typing as T

import gpxpy
import mapillary_tools.geo as geo

import mapillary_tools.geotag.gpmf_parser as gpmf_parser
import mapillary_tools.geotag.gps_filter as gps_filter
import mapillary_tools.utils as utils
from mapillary_tools import constants


def _convert_points_to_gpx_track(
    points: T.Sequence[gpmf_parser.PointWithFix],
) -> gpxpy.gpx.GPXTrack:
    gpx_track = gpxpy.gpx.GPXTrack()
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(gpx_segment)
    gps_fix_map = {
        gpmf_parser.GPSFix.NO_FIX: "none",
        gpmf_parser.GPSFix.FIX_2D: "2d",
        gpmf_parser.GPSFix.FIX_3D: "3d",
    }
    for idx, point in enumerate(points):
        if idx + 1 < len(points):
            next_point = points[idx + 1]
            distance = geo.gps_distance(
                (point.lat, point.lon),
                (next_point.lat, next_point.lon),
            )
            speed = gps_filter.calculate_point_speed(point, points[idx + 1])
        else:
            distance = 0.0
            speed = 0
        gpxp = gpxpy.gpx.GPXTrackPoint(
            point.lat,
            point.lon,
            elevation=point.alt,
            time=datetime.datetime.utcfromtimestamp(point.time),
            comment=f"precision: {point.gps_precision}; distance: {distance}; speed: {speed}; ground_speed: {point.gps_ground_speed}",
        )
        if point.gps_fix is not None:
            gpxp.type_of_gpx_fix = gps_fix_map.get(point.gps_fix)
        gpx_segment.points.append(gpxp)

    return gpx_track


def _filter_outliers(points: T.Sequence[gpmf_parser.PointWithFix]):
    distances = [
        geo.gps_distance((left.lat, left.lon), (right.lat, right.lon))
        for left, right in geo.pairwise(points)
    ]
    if len(distances) < 2:
        return points

    max_distance = gps_filter.upper_whisker(distances)
    max_distance = max(
        constants.GOPRO_GPS_PRECISION + constants.GOPRO_GPS_PRECISION, max_distance
    )
    subseqs = gps_filter.split_if(
        T.cast(T.List[geo.Point], points),
        gps_filter.farther_than(max_distance),
    )

    ground_speeds = [
        point.gps_ground_speed for point in points if point.gps_ground_speed is not None
    ]
    if len(ground_speeds) < 2:
        return points

    max_speed = gps_filter.upper_whisker(ground_speeds)
    merged = gps_filter.dbscan(subseqs, gps_filter.slower_than(max_speed))

    return T.cast(
        T.List[gpmf_parser.PointWithFix],
        gps_filter.find_majority(merged.values()),
    )


def _convert_gpx(
    gpx: gpxpy.gpx.GPX, path: pathlib.Path, gps_fix=None, max_precision=None
):
    points = gpmf_parser.parse_gpx(path)
    points = [
        p
        for p in points
        if (gps_fix is None or (p.gps_fix is None or p.gps_fix.value in gps_fix))
        and (
            max_precision is None
            or (p.gps_precision is None or p.gps_precision <= max_precision)
        )
    ]
    points = _filter_outliers(points)

    gpx_track = _convert_points_to_gpx_track(points)
    gpx_track.name = path.name
    gpx_track.comment = f"#points: {len(points)}"
    gpx.tracks.append(gpx_track)


def _convert_geojson(path: pathlib.Path, gps_fix=None, max_precision=None):
    points = gpmf_parser.parse_gpx(path)
    good_points = []
    outliers = []
    for p in points:
        if (gps_fix is None or (p.gps_fix is None or p.gps_fix.value in gps_fix)) and (
            max_precision is None
            or (p.gps_precision is None or p.gps_precision <= max_precision)
        ):
            good_points.append(p)
        else:
            outliers.append(p)

    features = []

    if good_points:
        coordinates = [[p.lon, p.lat] for p in good_points]
        linestring = {"type": "LineString", "coordinates": coordinates}
        features.append(
            {
                "type": "Feature",
                "geometry": linestring,
                "properties": {"name": path.name},
            }
        )

    for idx, p in enumerate(outliers):
        geomtry = {"type": "Point", "coordinates": [p.lon, p.lat]}
        properties = {
            "alt": p.alt,
            "fix": p.gps_fix.value if p.gps_fix is not None else None,
            "index": idx,
            "name": path.name,
            "precision": p.gps_precision,
            "time": p.time,
        }
        features.append(
            {
                "type": "Feature",
                "geometry": geomtry,
                "properties": properties,
            }
        )
    return features


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="+", help="Path to video file or directory")
    parser.add_argument(
        "--max_precision",
        type=int,
        help="Show GPS points under this Dilution of Precision (DOP x100)",
    )
    parser.add_argument("--gps_fix", help="Show GPS points with this GPS fix")
    parser.add_argument("--geojson", help="Print as GeoJSON", action="store_true")
    parser.add_argument(
        "--dump", help="Print as Construct structures", action="store_true"
    )
    return parser.parse_args()


def main():
    parsed_args = _parse_args()
    if parsed_args.gps_fix is not None:
        gps_fix = set(int(x) for x in parsed_args.gps_fix.split(","))
    else:
        gps_fix = None

    features = []
    gpx = gpxpy.gpx.GPX()

    for path in parsed_args.path:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                pp = pathlib.Path(p)
                if parsed_args.dump:
                    samples = list(gpmf_parser.dump_samples(pp))
                elif parsed_args.geojson:
                    features.extend(
                        _convert_geojson(pp, gps_fix, parsed_args.max_precision)
                    )
                else:
                    _convert_gpx(gpx, pp, gps_fix, parsed_args.max_precision)
        else:
            p = pathlib.Path(path)
            if parsed_args.dump:
                samples = list(gpmf_parser.dump_samples(p))
            elif parsed_args.geojson:
                features.extend(_convert_geojson(p, gps_fix, parsed_args.max_precision))
            else:
                _convert_gpx(gpx, p, gps_fix, parsed_args.max_precision)

    if parsed_args.dump:
        for sample in samples:
            print(sample)
    else:
        if features:
            print(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": features,
                    }
                )
            )
        else:
            print(gpx.to_xml())


if __name__ == "__main__":
    main()
