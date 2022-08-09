import logging
import os
import typing as T

import gpxpy
from tqdm import tqdm

from .geotag_from_generic import GeotagFromGeneric
from .geotag_from_gpx import GeotagFromGPXWithProgress

from .. import types, exif_read


LOG = logging.getLogger(__name__)


class GeotagFromGPXFile(GeotagFromGeneric):
    def __init__(
        self,
        image_dir: str,
        images: T.List[str],
        source_path: str,
        use_gpx_start_time: bool = False,
        offset_time: float = 0.0,
    ):
        super().__init__()
        tracks = parse_gpx(source_path)
        if 1 < len(tracks):
            LOG.warning(
                "Found %s tracks in the GPX file %s. Will merge points in all the tracks as a single track for interpolation",
                len(tracks),
                source_path,
            )
        self.points: T.List[types.GPXPoint] = sum(tracks, [])
        self.image_dir = image_dir
        self.images = images
        self.source_path = source_path
        self.use_gpx_start_time = use_gpx_start_time
        self.offset_time = offset_time

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
        with tqdm(
            total=len(self.images),
            desc=f"Interpolating",
            unit="images",
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        ) as pbar:
            geotag = GeotagFromGPXWithProgress(
                self.image_dir,
                self.images,
                self.points,
                use_gpx_start_time=self.use_gpx_start_time,
                offset_time=self.offset_time,
                progress_bar=pbar,
            )
            descs = geotag.to_description()

        return list(
            types.map_descs(
                self._attach_exif,
                tqdm(
                    descs,
                    desc=f"Processing",
                    unit="images",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                ),
            )
        )


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
