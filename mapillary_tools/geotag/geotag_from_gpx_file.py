import logging
import typing as T
from pathlib import Path

import gpxpy
from tqdm import tqdm

from .. import exif_read, geo, types

from .geotag_from_generic import GeotagFromGeneric
from .geotag_from_gpx import GeotagFromGPXWithProgress


LOG = logging.getLogger(__name__)


class GeotagFromGPXFile(GeotagFromGeneric):
    def __init__(
        self,
        images: T.Sequence[Path],
        source_path: Path,
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
        self.points: T.List[geo.Point] = sum(tracks, [])
        self.images = images
        self.source_path = source_path
        self.use_gpx_start_time = use_gpx_start_time
        self.offset_time = offset_time

    def _attach_exif(
        self, image_metadata: types.ImageMetadata
    ) -> types.ImageMetadataOrError:
        try:
            exif = exif_read.ExifRead(image_metadata.filename)
        except Exception as exc:
            LOG.warning(
                "Unknown error reading EXIF from image %s",
                image_metadata.filename,
                exc_info=True,
            )
            return types.describe_error_metadata(
                exc, image_metadata.filename, filetype=types.FileType.IMAGE
            )

        image_metadata.MAPOrientation = exif.extract_orientation()
        image_metadata.MAPDeviceMake = exif.extract_make()
        image_metadata.MAPDeviceModel = exif.extract_model()

        return image_metadata

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        with tqdm(
            total=len(self.images),
            desc="Interpolating",
            unit="images",
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        ) as pbar:
            geotag = GeotagFromGPXWithProgress(
                self.images,
                self.points,
                use_gpx_start_time=self.use_gpx_start_time,
                offset_time=self.offset_time,
                progress_bar=pbar,
            )
            metadatas = geotag.to_description()

        processed: T.List[types.ImageMetadataOrError] = []
        metadata_tqdm = tqdm(
            metadatas,
            desc="Processing",
            unit="images",
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        )
        for metadata in metadata_tqdm:
            if isinstance(metadata, types.ErrorMetadata):
                processed.append(metadata)
            else:
                modified = self._attach_exif(metadata)
                processed.append(modified)
        return processed


Track = T.List[geo.Point]


def parse_gpx(gpx_file: Path) -> T.List[Track]:
    with gpx_file.open("r") as f:
        gpx = gpxpy.parse(f)

    tracks: T.List[Track] = []

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
