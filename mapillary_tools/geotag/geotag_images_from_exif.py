import logging
import typing as T
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, geo, types, utils
from ..exif_read import ExifRead, ExifReadABC
from .geotag_from_generic import GeotagImagesFromGeneric

LOG = logging.getLogger(__name__)


class GeotagImagesFromEXIF(GeotagImagesFromGeneric):
    def __init__(
        self, image_paths: T.Sequence[Path], num_processes: T.Optional[int] = None
    ):
        self.image_paths = image_paths
        self.num_processes = num_processes
        super().__init__()

    @staticmethod
    def build_image_metadata(
        image_path: Path, exif: ExifReadABC, skip_lonlat_error: bool = False
    ) -> types.ImageMetadata:
        lonlat = exif.extract_lon_lat()
        if lonlat is None:
            if not skip_lonlat_error:
                raise exceptions.MapillaryGeoTaggingError(
                    "Unable to extract GPS Longitude or GPS Latitude from the image"
                )
            lonlat = (0.0, 0.0)
        lon, lat = lonlat

        capture_time = exif.extract_capture_time()
        if capture_time is None:
            raise exceptions.MapillaryGeoTaggingError(
                "Unable to extract timestamp from the image"
            )

        image_metadata = types.ImageMetadata(
            filename=image_path,
            filesize=utils.get_file_size(image_path),
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
                exif = ExifRead(fp)
                image_metadata = GeotagImagesFromEXIF.build_image_metadata(
                    image_path, exif, skip_lonlat_error=skip_lonlat_error
                )
        except Exception as ex:
            return types.describe_error_metadata(
                ex, image_path, filetype=types.FileType.IMAGE
            )

        return image_metadata

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
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
                    GeotagImagesFromEXIF.geotag_image,
                    self.image_paths,
                )
            else:
                image_metadatas_iter = pool.imap(
                    GeotagImagesFromEXIF.geotag_image,
                    self.image_paths,
                )
            return list(
                tqdm(
                    image_metadatas_iter,
                    desc="Extracting geotags from images",
                    unit="images",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                    total=len(self.image_paths),
                )
            )
