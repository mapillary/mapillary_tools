import typing as T
from pathlib import Path

import gpxpy

from .. import geo

Track = T.List[geo.Point]


def parse_gpx(gpx_file: Path) -> list[Track]:
    with gpx_file.open("r") as f:
        gpx = gpxpy.parse(f)

    tracks: list[Track] = []

    for track in gpx.tracks:
        for segment in track.segments:
            tracks.append([])
            for point in segment.points:
                if point.time is not None:
                    tracks[-1].append(
                        geo.Point(
                            time=geo.as_unix_time(point.time),
                            lat=point.latitude,
                            lon=point.longitude,
                            alt=point.elevation,
                            angle=None,
                        )
                    )

    return tracks
