import io
import logging
import typing as T
from multiprocessing import Pool
from pathlib import Path

import piexif

from tqdm import tqdm

from .. import exif_write, geo, types
from ..exceptions import MapillaryGeoTaggingError
from ..exif_read import ExifRead

from .geotag_from_generic import GeotagFromGeneric

LOG = logging.getLogger(__name__)


def verify_image_exif_write(
    metadata: types.ImageMetadata,
    image_data: T.Optional[bytes] = None,
) -> types.ImageMetadataOrError:
    if image_data is None:
        edit = exif_write.ExifEdit(metadata.filename)
    else:
        edit = exif_write.ExifEdit(image_data)

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

    @staticmethod
    def geotag_image(
        image_path: Path, skip_lonlat_error: bool = False
    ) -> types.ImageMetadataOrError:
        with image_path.open("rb") as fp:
            image_data = fp.read()
        image_bytesio = io.BytesIO(image_data)

        try:
            exif = ExifRead(image_bytesio)
        except Exception as ex:
            LOG.warning(
                "Unknown error reading EXIF from image %s",
                image_path,
                exc_info=True,
            )
            return types.describe_error_metadata(
                ex, image_path, filetype=types.FileType.IMAGE
            )

        lonlat = exif.extract_lon_lat()
        if lonlat is None:
            if not skip_lonlat_error:
                exc = MapillaryGeoTaggingError(
                    "Unable to extract GPS Longitude or GPS Latitude from the image"
                )
                return types.describe_error_metadata(
                    exc, image_path, filetype=types.FileType.IMAGE
                )
            lonlat = (0.0, 0.0)
        lon, lat = lonlat

        capture_time = exif.extract_capture_time()
        if capture_time is None:
            exc = MapillaryGeoTaggingError("Unable to extract timestamp from the image")
            return types.describe_error_metadata(
                exc, image_path, filetype=types.FileType.IMAGE
            )

        image_metadata = types.ImageMetadata(
            filename=image_path,
            md5sum=None,
            time=geo.as_unix_time(capture_time),
            lat=lat,
            lon=lon,
            alt=exif.extract_altitude(),
            angle=exif.extract_direction(),
            width=exif.extract_width(),
            height=exif.extract_height(),
            MAPOrientation=exif.extract_orientation(),
            MAPDeviceMake=exif.extract_make(),
            MAPDeviceModel=exif.extract_model(),
        )

        image_bytesio.seek(0, io.SEEK_SET)
        image_metadata.update_md5sum(image_bytesio)

        image_bytesio.seek(0, io.SEEK_SET)
        image_metadata_or_error = verify_image_exif_write(
            image_metadata,
            image_data=image_bytesio.read(),
        )

        return image_metadata_or_error

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        with Pool() as pool:
            image_metadatas = pool.imap(
                GeotagFromEXIF.geotag_image,
                self.image_paths,
            )
            return list(
                tqdm(
                    image_metadatas,
                    desc="Extracting geotags from images",
                    unit="images",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                    total=len(self.image_paths),
                )
            )
