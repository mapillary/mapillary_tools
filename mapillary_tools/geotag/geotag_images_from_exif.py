import logging
import typing as T

from .base import GeotagImagesFromGeneric
from .image_extractors.exif import ImageEXIFExtractor

LOG = logging.getLogger(__name__)


class GeotagImagesFromEXIF(GeotagImagesFromGeneric):
    def _generate_image_extractors(self) -> T.Sequence[ImageEXIFExtractor]:
        return [ImageEXIFExtractor(path) for path in self.image_paths]
