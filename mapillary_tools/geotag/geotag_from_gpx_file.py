import logging
import os
import typing as T

import gpxpy

from .geotag_from_gpx import GeotagFromGPX
from .. import types, exif_read


LOG = logging.getLogger(__name__)


class GeotagFromGPXFile(GeotagFromGPX):
    def __init__(
        self,
        image_dir: str,
        images: T.List[str],
        source_path: str,
        use_gpx_start_time: bool = False,
        offset_time: float = 0.0,
    ):
        if not os.path.isfile(source_path):
            raise RuntimeError(f"GPX file not found: {source_path}")
        tracks = parse_gpx(source_path)
        if 1 < len(tracks):
            LOG.warning(
                "Found %s tracks in the GPX file %s. Will merge points in all the tracks as a single track for interpolation",
                len(tracks),
                source_path,
            )
        points: T.List[types.GPXPoint] = sum(tracks, [])
        super().__init__(
            image_dir,
            images,
            points,
            use_gpx_start_time=use_gpx_start_time,
            offset_time=offset_time,
        )

    def _attach_exif(
        self, desc: types.ImageDescriptionFile
    ) -> types.ImageDescriptionFileOrError:
        image_path = os.path.join(self.image_dir, desc["filename"])

        try:
            exif = exif_read.ExifRead(image_path)
        except Exception as exc:
            LOG.warning(
                "Unknown error reading EXIF from image %s",
                image_path,
                exc_info=True,
            )
            return {"error": types.describe_error(exc), "filename": desc["filename"]}

        meta: types.MetaProperties = {
            "MAPOrientation": exif.extract_orientation(),
        }
        make = exif.extract_make()
        if make is not None:
            meta["MAPDeviceMake"] = make

        model = exif.extract_model()
        if model is not None:
            meta["MAPDeviceModel"] = model

        return T.cast(types.ImageDescriptionFile, {**desc, **meta})

    def to_description(self) -> T.List[types.ImageDescriptionFileOrError]:
        descs = super().to_description()
        return list(types.map_descs(self._attach_exif, descs))


Track = T.List[types.GPXPoint]


def parse_gpx(gpx_file: str) -> T.List[Track]:
    with open(gpx_file, "r") as f:
        gpx = gpxpy.parse(f)

    tracks: T.List[Track] = []

    for track in gpx.tracks:
        for segment in track.segments:
            tracks.append([])
            for point in segment.points:
                tracks[-1].append(
                    types.GPXPoint(
                        point.time.replace(tzinfo=None),
                        lat=point.latitude,
                        lon=point.longitude,
                        alt=point.elevation,
                    )
                )

    return tracks
