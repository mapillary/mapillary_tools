from __future__ import annotations

import logging
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

import gpxpy

from .. import exiftool_read, geo, utils

Track = T.List[geo.Point]
LOG = logging.getLogger(__name__)


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


def index_rdf_description_by_path(
    xml_paths: T.Sequence[Path],
) -> dict[str, ET.Element]:
    rdf_description_by_path: dict[str, ET.Element] = {}

    for xml_path in utils.find_xml_files(xml_paths):
        try:
            etree = ET.parse(xml_path)
        except ET.ParseError as ex:
            verbose = LOG.getEffectiveLevel() <= logging.DEBUG
            if verbose:
                LOG.warning("Failed to parse %s", xml_path, exc_info=True)
            else:
                LOG.warning("Failed to parse %s: %s", xml_path, ex)
            continue

        rdf_description_by_path.update(
            exiftool_read.index_rdf_description_by_path_from_xml_element(
                etree.getroot()
            )
        )

    return rdf_description_by_path
