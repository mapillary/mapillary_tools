import contextlib
import logging
import typing as T
from pathlib import Path

from .. import exceptions, geo, types, utils
from ..exif_read import ExifRead, ExifReadABC
from .geotag_from_generic import GenericImageExtractor, GeotagImagesFromGeneric

LOG = logging.getLogger(__name__)


class ImageEXIFExtractor(GenericImageExtractor):
    def __init__(self, image_path: Path, skip_lonlat_error: bool = False):
        super().__init__(image_path)
        self.skip_lonlat_error = skip_lonlat_error

    @contextlib.contextmanager
    def _exif_context(self) -> T.Generator[ExifReadABC, None, None]:
        with self.image_path.open("rb") as fp:
            yield ExifRead(fp)

    def extract(self) -> types.ImageMetadata:
        with self._exif_context() as exif:
            lonlat = exif.extract_lon_lat()
            if lonlat is None:
                if not self.skip_lonlat_error:
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
                filename=self.image_path,
                filesize=utils.get_file_size(self.image_path),
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


class GeotagImagesFromEXIF(GeotagImagesFromGeneric):
    def _generate_image_extractors(self) -> T.Sequence[ImageEXIFExtractor]:
        return [ImageEXIFExtractor(path) for path in self.image_paths]
