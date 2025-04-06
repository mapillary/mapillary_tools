from __future__ import annotations

import abc
import logging
import typing as T
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, types, utils
from .image_extractors.base import BaseImageExtractor
from .video_extractors.base import BaseVideoExtractor


LOG = logging.getLogger(__name__)


TImageExtractor = T.TypeVar("TImageExtractor", bound=BaseImageExtractor)


class GeotagImagesFromGeneric(abc.ABC, T.Generic[TImageExtractor]):
    """
    Extracts metadata from a list of image files with multiprocessing.
    """

    def __init__(self, num_processes: int | None = None) -> None:
        self.num_processes = num_processes

    def to_description(
        self, image_paths: T.Sequence[Path]
    ) -> list[types.ImageMetadataOrError]:
        extractor_or_errors = self._generate_image_extractors(image_paths)

        assert len(extractor_or_errors) == len(image_paths)

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
        except exceptions.MapillaryUserError as ex:
            # Considered as fatal error if not MapillaryDescriptionError
            raise ex
        except Exception as ex:
            # TODO: hide details if not verbose mode
            LOG.exception("Unexpected error extracting metadata from %s", image_path)
            return types.describe_error_metadata(
                ex, image_path, filetype=types.FileType.IMAGE
            )

    def _generate_image_extractors(
        self, image_paths: T.Sequence[Path]
    ) -> T.Sequence[TImageExtractor | types.ErrorMetadata]:
        raise NotImplementedError


TVideoExtractor = T.TypeVar("TVideoExtractor", bound=BaseVideoExtractor)


class GeotagVideosFromGeneric(abc.ABC, T.Generic[TVideoExtractor]):
    """
    Extracts metadata from a list of video files with multiprocessing.
    """

    def __init__(self, num_processes: int | None = None) -> None:
        self.num_processes = num_processes

    def to_description(
        self, video_paths: T.Sequence[Path]
    ) -> list[types.VideoMetadataOrError]:
        extractor_or_errors = self._generate_video_extractors(video_paths)

        assert len(extractor_or_errors) == len(video_paths)

        extractors, error_metadatas = types.separate_errors(extractor_or_errors)

        map_results = utils.mp_map_maybe(
            self.run_extraction,
            extractors,
            num_processes=self.num_processes,
        )

        results = list(
            tqdm(
                map_results,
                desc="Extracting videos",
                unit="videos",
                disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                total=len(extractors),
            )
        )

        return results + error_metadatas

    # This method is passed to multiprocessing
    # so it has to be classmethod or staticmethod to avoid pickling the instance
    @classmethod
    def run_extraction(cls, extractor: TVideoExtractor) -> types.VideoMetadataOrError:
        video_path = extractor.video_path

        try:
            return extractor.extract()
        except exceptions.MapillaryDescriptionError as ex:
            return types.describe_error_metadata(
                ex, video_path, filetype=types.FileType.VIDEO
            )
        except exceptions.MapillaryUserError as ex:
            # Considered as fatal error if not MapillaryDescriptionError
            raise ex
        except Exception as ex:
            # TODO: hide details if not verbose mode
            LOG.exception("Unexpected error extracting metadata from %s", video_path)
            return types.describe_error_metadata(
                ex, video_path, filetype=types.FileType.VIDEO
            )

    def _generate_video_extractors(
        self, video_paths: T.Sequence[Path]
    ) -> T.Sequence[TVideoExtractor | types.ErrorMetadata]:
        raise NotImplementedError
