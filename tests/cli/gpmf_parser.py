import argparse
import datetime
import json
import pathlib
import typing as T

import gpxpy
import gpxpy.gpx
import mapillary_tools.geo as geo

import mapillary_tools.geotag.gpmf_parser as gpmf_parser
import mapillary_tools.geotag.gps_filter as gps_filter
import mapillary_tools.utils as utils


def _convert_points_to_gpx_track_segment(
    points: T.Sequence[gpmf_parser.PointWithFix],
) -> gpxpy.gpx.GPXTrackSegment:
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
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

        # GPX spec has no speed https://www.topografix.com/GPX/1/1/#type_wptType
        # so write them in comment as JSON
        comment = json.dumps(
            {
                "distance_between": distance,
                "speed_between": speed,
                "ground_speed": point.gps_ground_speed,
            }
        )
        gpxp = gpxpy.gpx.GPXTrackPoint(
            point.lat,
            point.lon,
            elevation=point.alt,
            time=datetime.datetime.utcfromtimestamp(point.time),
            position_dilution=point.gps_precision,
            comment=comment,
        )
        if point.gps_fix is not None:
            gpxp.type_of_gpx_fix = gps_fix_map.get(point.gps_fix)
        gpx_segment.points.append(gpxp)

    return gpx_segment


def _convert_gpx(gpx: gpxpy.gpx.GPX, path: pathlib.Path):
    points = gpmf_parser.parse_gpx(path)
    gpx_track = gpxpy.gpx.GPXTrack()
    gpx_track_segment = _convert_points_to_gpx_track_segment(points)
    gpx_track.segments.append(gpx_track_segment)
    gpx_track.name = path.name
    gpx_track.comment = f"#points: {len(points)}"
    with path.open("rb") as fp:
        device_names = gpmf_parser.extract_all_device_names(fp)
    with path.open("rb") as fp:
        model = gpmf_parser.extract_camera_model(fp)
    gpx_track.description = (
        f'Extracted from model "{model}" among these devices {device_names}'
    )
    gpx.tracks.append(gpx_track)


def _convert_geojson(path: pathlib.Path):
    features = []
    points = gpmf_parser.parse_gpx(path)

    for idx, p in enumerate(points):
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
    parser.add_argument("--geojson", help="Print as GeoJSON", action="store_true")
    parser.add_argument(
        "--dump", help="Print as Construct structures", action="store_true"
    )
    return parser.parse_args()


def main():
    parsed_args = _parse_args()

    features = []
    samples = []
    gpx = gpxpy.gpx.GPX()

    def _process(path: pathlib.Path):
        if parsed_args.dump:
            with path.open("rb") as fp:
                samples.extend(gpmf_parser.iterate_gpmd_sample_data(fp))
        elif parsed_args.geojson:
            features.extend(_convert_geojson(path))
        else:
            _convert_gpx(gpx, path)

    for path in utils.find_videos([pathlib.Path(p) for p in parsed_args.path]):
        _process(path)

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
