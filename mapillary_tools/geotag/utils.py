# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import logging
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

import gpxpy

from .. import exiftool_read, geo, telemetry, utils

Track = T.List[geo.Point]
LOG = logging.getLogger(__name__)

# GPS epoch start: January 6, 1980 (Unix timestamp).
# Any timestamp below this is not a valid GPS time.
_MIN_GPS_EPOCH_TIME = 315964800.0


def parse_gpx(gpx_file: Path) -> list[Track]:
    with gpx_file.open("r") as f:
        gpx = gpxpy.parse(f)

    tracks: list[Track] = []

    for track in gpx.tracks:
        for segment in track.segments:
            tracks.append([])
            for point in segment.points:
                if point.time is not None:
                    unix_time = geo.as_unix_time(point.time)
                    if unix_time >= _MIN_GPS_EPOCH_TIME:
                        tracks[-1].append(
                            telemetry.CAMMGPSPoint(
                                time=unix_time,
                                lat=point.latitude,
                                lon=point.longitude,
                                alt=point.elevation,
                                angle=None,
                                time_gps_epoch=unix_time,
                                gps_fix_type=3 if point.elevation is not None else 2,
                                horizontal_accuracy=0.0,
                                vertical_accuracy=0.0,
                                velocity_east=0.0,
                                velocity_north=0.0,
                                velocity_up=0.0,
                                speed_accuracy=0.0,
                            )
                        )
                    else:
                        tracks[-1].append(
                            geo.Point(
                                time=unix_time,
                                lat=point.latitude,
                                lon=point.longitude,
                                alt=point.elevation,
                                angle=None,
                            )
                        )

    return tracks


def index_rdf_description_by_path(xml_paths: T.Sequence[Path]) -> dict[str, ET.Element]:
    rdf_by_path: dict[str, ET.Element] = {}

    for xml_path in utils.find_xml_files(xml_paths):
        try:
            etree = ET.parse(xml_path)
        except Exception as ex:
            LOG.warning(
                f"Failed to parse {xml_path}: {ex}",
                exc_info=LOG.isEnabledFor(logging.DEBUG),
            )
            continue

        rdf_by_path.update(
            exiftool_read.index_rdf_description_by_path_from_xml_element(
                etree.getroot()
            )
        )

    return rdf_by_path
