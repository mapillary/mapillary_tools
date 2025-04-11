from __future__ import annotations

import logging
from pathlib import Path

from . import utils
from .geotag_images_from_gpx import GeotagImagesFromGPX


LOG = logging.getLogger(__name__)


class GeotagImagesFromGPXFile(GeotagImagesFromGPX):
    def __init__(
        self,
        source_path: Path,
        use_gpx_start_time: bool = False,
        offset_time: float = 0.0,
        num_processes: int | None = None,
    ):
        try:
            tracks = utils.parse_gpx(source_path)
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
            points,
            use_gpx_start_time=use_gpx_start_time,
            offset_time=offset_time,
            num_processes=num_processes,
        )
