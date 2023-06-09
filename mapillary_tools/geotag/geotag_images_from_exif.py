import io
import logging
import typing as T
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from .. import exif_write, geo, types
from ..exceptions import MapillaryGeoTaggingError
from ..exif_read import ExifRead, ExifReadABC
from .geotag_from_generic import GeotagImagesFromGeneric

LOG = logging.getLogger(__name__)


def verify_image_exif_write(
    metadata: types.ImageMetadata,
    image_data: T.Optional[bytes] = None,
) -> None:
    if image_data is None:
        edit = exif_write.ExifEdit(metadata.filename)
    else:
        edit = exif_write.ExifEdit(image_data)

    # The cast is to fix the type error in Python3.6:
    # Argument 1 to "add_image_description" of "ExifEdit" has incompatible type "ImageDescription"; expected "Dict[str, Any]"
    edit.add_image_description(
        T.cast(T.Dict, types.desc_file_to_exif(types.as_desc(metadata)))
    )

    # Possible errors thrown here:
    # - struct.error: 'H' format requires 0 <= number <= 65535
    # - piexif.InvalidImageDataError
    edit.dump_image_bytes()


class GeotagFromEXIF(GeotagImagesFromGeneric):
    def __init__(self, image_paths: T.Sequence[Path]):
        self.image_paths = image_paths
        super().__init__()

    @staticmethod
    def build_image_metadata(
        image_path: Path, exif: ExifReadABC, skip_lonlat_error: bool = False
    ) -> types.ImageMetadata:
        lonlat = exif.extract_lon_lat()
        if lonlat is None:
            if not skip_lonlat_error:
                raise MapillaryGeoTaggingError(
                    "Unable to extract GPS Longitude or GPS Latitude from the image"
                )
            lonlat = (0.0, 0.0)
        lon, lat = lonlat

        capture_time = exif.extract_capture_time()
        if capture_time is None:
            raise MapillaryGeoTaggingError("Unable to extract timestamp from the image")

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

        return image_metadata

    @staticmethod
    def geotag_image(
        image_path: Path, skip_lonlat_error: bool = False
    ) -> types.ImageMetadataOrError:
        try:
            with image_path.open("rb") as fp:
                image_bytesio = io.BytesIO(fp.read())
            exif = ExifRead(image_bytesio)
            image_metadata = GeotagFromEXIF.build_image_metadata(
                image_path, exif, skip_lonlat_error=skip_lonlat_error
            )
            image_bytesio.seek(0, io.SEEK_SET)
            verify_image_exif_write(
                image_metadata,
                image_data=image_bytesio.read(),
            )
        except Exception as ex:
            return types.describe_error_metadata(
                ex, image_path, filetype=types.FileType.IMAGE
            )

        image_bytesio.seek(0, io.SEEK_SET)
        image_metadata.update_md5sum(image_bytesio)

        return image_metadata

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
