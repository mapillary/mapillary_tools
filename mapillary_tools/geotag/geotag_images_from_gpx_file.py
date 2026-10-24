# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import logging
from pathlib import Path

import gpxpy

from .. import exceptions, geo
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
        track_error: Exception | None = None
        try:
            points = _read_gpx_points(source_path)
        except exceptions.MapillaryInvalidGPXError as ex:
            points, track_error = [], ex

        super().__init__(
            points,
            use_gpx_start_time=use_gpx_start_time,
            offset_time=offset_time,
            num_processes=num_processes,
        )
        self.track_error = track_error


def _read_gpx_points(source_path: Path) -> list[geo.Point]:
    """
    Read the points of a GPX file, merged into one track. Raise
    MapillaryInvalidGPXError if the file cannot be parsed, as for a video
    geotagged from it, and if it is missing or has no timestamped point: the
    file was given to geotag the images from, so it fails them rather than
    leaving them to the next geotag source.

    The file is parsed once in a process (see utils.read_gpx_tracks()), and
    its points are shared with its other readers, which must not change them.
    """
    if not source_path.is_file():
        raise exceptions.MapillaryInvalidGPXError(f"GPX file not found: {source_path}")

    try:
        tracks = utils.read_gpx_tracks(source_path)
    except (OSError, UnicodeError, gpxpy.gpx.GPXException) as ex:
        raise exceptions.MapillaryInvalidGPXError(
            f"{source_path.name} is not a valid GPX file. "
            "Replace it with a valid GPX file."
        ) from ex

    if 1 < len(tracks):
        utils.warn_once(
            source_path,
            ("tracks", len(tracks)),
            "Found %s tracks in the GPX file %s. Will merge points in all the tracks as a single track for interpolation",
            len(tracks),
            source_path,
        )
    points: list[geo.Point] = [point for track in tracks for point in track]

    if not points:
        raise exceptions.MapillaryInvalidGPXError(
            f"No timestamped points found in the GPX file {source_path}"
        )

    return points
