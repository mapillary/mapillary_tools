from __future__ import annotations

import abc
import logging
import typing as T
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, types, utils


LOG = logging.getLogger(__name__)


class GenericImageExtractor(abc.ABC):
    """
    Extracts metadata from an image file.
    """

    def __init__(self, image_path: Path):
        self.image_path = image_path

    def extract(self) -> types.ImageMetadataOrError:
        raise NotImplementedError


TImageExtractor = T.TypeVar("TImageExtractor", bound=GenericImageExtractor)


class GeotagImagesFromGeneric(abc.ABC, T.Generic[TImageExtractor]):
    """
    Extracts metadata from a list of image files with multiprocessing.
    """

    def __init__(
        self, image_paths: T.Sequence[Path], num_processes: int | None
    ) -> None:
        self.image_paths = image_paths
        self.num_processes = num_processes

    def to_description(self) -> list[types.ImageMetadataOrError]:
        extractor_or_errors = self._generate_image_extractors()

        assert len(extractor_or_errors) == len(self.image_paths)

        extractors, error_metadatas = types.separate_errors(extractor_or_errors)

        map_results = utils.mp_map_maybe(
            self.run_extraction,
            extractors,
            num_processes=self.num_processes,
        )

        results = list(
            tqdm(
                map_results,
                desc="Extracting images",
                unit="images",
                disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                total=len(extractors),
            )
        )

        return results + error_metadatas

    def _generate_image_extractors(
        self,
    ) -> T.Sequence[TImageExtractor | types.ErrorMetadata]:
        raise NotImplementedError

    # This method is passed to multiprocessing
    # so it has to be classmethod or staticmethod to avoid pickling the instance
    @classmethod
    def run_extraction(cls, extractor: TImageExtractor) -> types.ImageMetadataOrError:
        image_path = extractor.image_path

        try:
            return extractor.extract()
        except exceptions.MapillaryDescriptionError as ex:
            return types.describe_error_metadata(
                ex, image_path, filetype=types.FileType.IMAGE
            )
        except Exception as ex:
            LOG.exception("Unexpected error extracting metadata from %s", image_path)
            return types.describe_error_metadata(
                ex, image_path, filetype=types.FileType.IMAGE
            )


class GeotagVideosFromGeneric(abc.ABC):
    def __init__(self) -> None:
        pass

    @abc.abstractmethod
    def to_description(self) -> list[types.VideoMetadataOrError]:
        raise NotImplementedError
