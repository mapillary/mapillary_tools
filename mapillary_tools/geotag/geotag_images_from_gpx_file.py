import dataclasses
import logging
import typing as T
from multiprocessing import Pool
from pathlib import Path

import gpxpy
from tqdm import tqdm

from .. import exif_read, geo, types
from .geotag_from_generic import GeotagImagesFromGeneric
from .geotag_images_from_gpx import GeotagImagesFromGPXWithProgress


LOG = logging.getLogger(__name__)


class GeotagImagesFromGPXFile(GeotagImagesFromGeneric):
    def __init__(
        self,
        image_paths: T.Sequence[Path],
        source_path: Path,
        use_gpx_start_time: bool = False,
        offset_time: float = 0.0,
        num_processes: T.Optional[int] = None,
    ):
        super().__init__()
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
        self.points: T.List[geo.Point] = sum(tracks, [])
        self.image_paths = image_paths
        self.source_path = source_path
        self.use_gpx_start_time = use_gpx_start_time
        self.offset_time = offset_time
        self.num_processes = num_processes

    @staticmethod
    def _extract_image_metadata(
        image_metadata: types.ImageMetadata,
    ) -> types.ImageMetadataOrError:
        try:
            exif = exif_read.ExifRead(image_metadata.filename)
            orientation = exif.extract_orientation()
            make = exif.extract_make()
            model = exif.extract_model()
        except Exception as ex:
            return types.describe_error_metadata(
                ex, image_metadata.filename, filetype=types.FileType.IMAGE
            )

        return dataclasses.replace(
            image_metadata,
            MAPOrientation=orientation,
            MAPDeviceMake=make,
            MAPDeviceModel=model,
        )

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        with tqdm(
            total=len(self.image_paths),
            desc="Interpolating",
            unit="images",
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        ) as pbar:
            geotag = GeotagImagesFromGPXWithProgress(
                self.image_paths,
                self.points,
                use_gpx_start_time=self.use_gpx_start_time,
                offset_time=self.offset_time,
                progress_bar=pbar,
            )
            image_metadata_or_errors = geotag.to_description()

        image_metadatas: T.List[types.ImageMetadata] = []
        error_metadatas: T.List[types.ErrorMetadata] = []
        for metadata in image_metadata_or_errors:
            if isinstance(metadata, types.ErrorMetadata):
                error_metadatas.append(metadata)
            else:
                image_metadatas.append(metadata)

        if self.num_processes is None:
            num_processes = self.num_processes
            disable_multiprocessing = False
        else:
            num_processes = max(self.num_processes, 1)
            disable_multiprocessing = self.num_processes <= 0

        with Pool(processes=num_processes) as pool:
            image_metadatas_iter: T.Iterator[types.ImageMetadataOrError]
            if disable_multiprocessing:
                image_metadatas_iter = map(
                    GeotagImagesFromGPXFile._extract_image_metadata, image_metadatas
                )
            else:
                # Do not pass error metadatas where the error object can not be pickled for multiprocessing to work
                # Otherwise we get:
                # TypeError: __init__() missing 3 required positional arguments: 'image_time', 'gpx_start_time', and 'gpx_end_time'
                # See https://stackoverflow.com/a/61432070
                image_metadatas_iter = pool.imap(
                    GeotagImagesFromGPXFile._extract_image_metadata, image_metadatas
                )
            image_metadata_or_errors = list(
                tqdm(
                    image_metadatas_iter,
                    desc="Processing",
                    unit="images",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                )
            )

        return (
            T.cast(T.List[types.ImageMetadataOrError], error_metadatas)
            + image_metadata_or_errors
        )


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
