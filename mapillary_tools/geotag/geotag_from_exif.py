import logging
import typing as T
from pathlib import Path

from tqdm import tqdm

from .. import geo, types
from ..exceptions import MapillaryGeoTaggingError
from ..exif_read import ExifRead

from .geotag_from_generic import GeotagFromGeneric

LOG = logging.getLogger(__name__)


class GeotagFromEXIF(GeotagFromGeneric):
    def __init__(self, image_paths: T.Sequence[Path]):
        self.image_paths = image_paths
        super().__init__()

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        metadatas: T.List[types.ImageMetadataOrError] = []

        image_path: Path
        for image_path in tqdm(
            self.image_paths,
            desc=f"Extracting geotags from images",
            unit="images",
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        ):
            try:
                exif = ExifRead(image_path)
            except Exception as exc0:
                LOG.warning(
                    "Unknown error reading EXIF from image %s",
                    image_path,
                    exc_info=True,
                )
                metadatas.append(
                    types.describe_error_metadata(
                        exc0, image_path, filetype=types.FileType.IMAGE
                    )
                )
                continue

            lon, lat = exif.extract_lon_lat()
            if lat is None or lon is None:
                exc = MapillaryGeoTaggingError(
                    "Unable to extract GPS Longitude or GPS Latitude from the image"
                )
                metadatas.append(
                    types.describe_error_metadata(
                        exc, image_path, filetype=types.FileType.IMAGE
                    )
                )
                continue

            timestamp = exif.extract_capture_time()
            if timestamp is None:
                exc = MapillaryGeoTaggingError(
                    "Unable to extract timestamp from the image"
                )
                metadatas.append(
                    types.describe_error_metadata(
                        exc, image_path, filetype=types.FileType.IMAGE
                    )
                )
                continue

            image_metadata = types.ImageMetadata(
                filename=image_path,
                lat=lat,
                lon=lon,
                alt=exif.extract_altitude(),
                angle=exif.extract_direction(),
                time=geo.as_unix_time(timestamp),
                MAPOrientation=exif.extract_orientation(),
                MAPDeviceMake=exif.extract_make(),
                MAPDeviceModel=exif.extract_model(),
            )

            metadatas.append(image_metadata)

        return metadatas
