from __future__ import annotations

import logging
import typing as T
from pathlib import Path

import gpxpy

from .. import geo
from .geotag_images_from_gpx import GeotagImagesFromGPX


LOG = logging.getLogger(__name__)


class GeotagImagesFromGPXFile(GeotagImagesFromGPX):
    def __init__(
        self,
        image_paths: T.Sequence[Path],
        source_path: Path,
        use_gpx_start_time: bool = False,
        offset_time: float = 0.0,
        num_processes: int | None = None,
    ):
        try:
            tracks = parse_gpx(source_path)
        except Exception as ex:
            raise RuntimeError(
                f"Error parsing GPX {source_path}: {ex.__class__.__name__}: {ex}"
            )

        if 1 < len(tracks):
            LOG.warning(
                "Found %s tracks in the GPX file %s. Will merge points in all the tracks as a single track for interpolation",
                len(tracks),
                source_path,
            )
        points = sum(tracks, [])
        super().__init__(
            image_paths,
            points,
            use_gpx_start_time=use_gpx_start_time,
            offset_time=offset_time,
            num_processes=num_processes,
        )


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
