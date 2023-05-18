import logging
import typing as T
from pathlib import Path

import piexif

from tqdm import tqdm

from .. import exif_write, geo, types, utils
from ..exceptions import MapillaryGeoTaggingError
from ..exif_read import ExifRead

from .geotag_from_generic import GeotagFromGeneric

LOG = logging.getLogger(__name__)


def verify_image_exif_write(
    metadata: types.ImageMetadata,
) -> types.ImageMetadataOrError:
    edit = exif_write.ExifEdit(metadata.filename)
    # The cast is to fix the type error in Python3.6:
    # Argument 1 to "add_image_description" of "ExifEdit" has incompatible type "ImageDescription"; expected "Dict[str, Any]"
    edit.add_image_description(
        T.cast(T.Dict, types.desc_file_to_exif(types.as_desc(metadata)))
    )
    try:
        edit.dump_image_bytes()
    except piexif.InvalidImageDataError as exc:
        return types.describe_error_metadata(
            exc,
            metadata.filename,
            filetype=types.FileType.IMAGE,
        )
    except Exception as exc:
        # possible error here: struct.error: 'H' format requires 0 <= number <= 65535
        LOG.warning(
            "Unknown error test writing image %s", metadata.filename, exc_info=True
        )
        return types.describe_error_metadata(
            exc,
            metadata.filename,
            filetype=types.FileType.IMAGE,
        )
    return metadata


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

            lonlat = exif.extract_lon_lat()
            if lonlat is None:
                exc = MapillaryGeoTaggingError(
                    "Unable to extract GPS Longitude or GPS Latitude from the image"
                )
                metadatas.append(
                    types.describe_error_metadata(
                        exc, image_path, filetype=types.FileType.IMAGE
                    )
                )
                continue
            lon, lat = lonlat

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

            with image_path.open("rb") as fp:
                md5sum = utils.md5sum_fp(fp)

            image_metadata = types.ImageMetadata(
                filename=image_path,
                lat=lat,
                lon=lon,
                alt=exif.extract_altitude(),
                angle=exif.extract_direction(),
                time=geo.as_unix_time(timestamp),
                md5sum=md5sum,
                width=exif.extract_width(),
                height=exif.extract_height(),
                MAPOrientation=exif.extract_orientation(),
                MAPDeviceMake=exif.extract_make(),
                MAPDeviceModel=exif.extract_model(),
            )

            image_metadata_or_error = verify_image_exif_write(image_metadata)

            metadatas.append(image_metadata_or_error)

        return metadatas
