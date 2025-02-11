import logging
import typing as T
from multiprocessing import Pool
from pathlib import Path

import tqdm

from .. import exceptions, geo, utils
from ..geotag import gpmf_gps_filter, utils as video_utils
from ..telemetry import GPSPoint
from ..types import (
    ErrorMetadata,
    FileType,
    MetadataOrError,
    VideoMetadata,
    VideoMetadataOrError,
)
from . import video_data_parser_factory
from .cli_options import CliOptions
from .extractors.base_parser import BaseParser


LOG = logging.getLogger(__name__)


class VideoDataExtractor:
    options: CliOptions

    def __init__(self, options: CliOptions) -> None:
        self.options = options

    def process(self) -> T.List[MetadataOrError]:
        paths = self.options["paths"]
        self._check_paths(paths)
        video_files = utils.find_videos(paths)
        self._check_sources_cardinality(video_files)

        num_processes = self.options["num_processes"] or None
        with Pool(processes=num_processes) as pool:
            if num_processes == 1:
                iter: T.Iterator[VideoMetadataOrError] = map(
                    self.process_file, video_files
                )
            else:
                iter = pool.imap(self.process_file, video_files)

            video_metadata_or_errors = list(
                tqdm.tqdm(
                    iter,
                    desc="Extracting GPS tracks",
                    unit="videos",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                    total=len(video_files),
                )
            )

        return video_metadata_or_errors

    def process_file(self, file: Path) -> VideoMetadataOrError:
        parsers = video_data_parser_factory.make_parsers(file, self.options)
        points: T.Sequence[geo.Point] = []
        make = self.options["device_make"]
        model = self.options["device_model"]

        ex: T.Optional[Exception]
        for parser in parsers:
            log_vars = {
                "filename": file,
                "parser": parser.parser_label,
                "source": parser.geotag_source_path,
            }
            try:
                if not points:
                    points = self._extract_points(parser, log_vars)
                if not model:
                    model = parser.extract_model()
                if not make:
                    make = parser.extract_make()
            except Exception as e:
                ex = e
                LOG.warning(
                    '%(filename)s: Exception for parser %(parser)s while processing source %(source)s: "%(e)s"',
                    {**log_vars, "e": e},
                )

        # After trying all parsers, return the points if we found any, otherwise
        # the last exception thrown or a default one.
        # Note that if we have points, we return them, regardless of exceptions
        # with make or model.
        if points:
            video_metadata = VideoMetadata(
                filename=file,
                filetype=FileType.VIDEO,
                md5sum=None,
                filesize=utils.get_file_size(file),
                points=points,
                make=make,
                model=model,
            )
            video_metadata.update_md5sum()
            return video_metadata
        else:
            return ErrorMetadata(
                filename=file,
                error=(
                    ex
                    if ex
                    else exceptions.MapillaryVideoGPSNotFoundError(
                        "No GPS data found from the video"
                    )
                ),
                filetype=FileType.VIDEO,
            )

    def _extract_points(
        self, parser: BaseParser, log_vars: T.Dict
    ) -> T.Sequence[geo.Point]:
        points = parser.extract_points()
        if points:
            LOG.debug(
                "%(filename)s: %(points)d points extracted by parser %(parser)s from file %(source)s}",
                {**log_vars, "points": len(points)},
            )

        return self._sanitize_points(points)

    @staticmethod
    def _check_paths(import_paths: T.Sequence[Path]):
        for path in import_paths:
            if not path.is_file() and not path.is_dir():
                raise exceptions.MapillaryFileNotFoundError(
                    f"Import file or directory not found: {path}"
                )

    def _check_sources_cardinality(self, files: T.Sequence[Path]):
        if len(files) > 1:
            for parser_opts in self.options["geotag_sources_options"]:
                pattern = parser_opts.get("pattern")
                if pattern and "%" not in pattern:
                    raise exceptions.MapillaryUserError(
                        "Multiple video files found: Geotag source pattern for source %s must include filename placeholders",
                        parser_opts["source"],
                    )

    @staticmethod
    def _sanitize_points(points: T.Sequence[geo.Point]) -> T.Sequence[geo.Point]:
        """
        Deduplicates points, when possible removes noisy ones, and checks
        against stationary videos
        """

        if not points:
            raise exceptions.MapillaryVideoGPSNotFoundError(
                "No GPS data found in the given sources"
            )

        points = geo.extend_deduplicate_points(points)

        if all(isinstance(p, GPSPoint) for p in points):
            points = T.cast(
                T.Sequence[geo.Point],
                gpmf_gps_filter.remove_noisy_points(
                    T.cast(T.Sequence[GPSPoint], points)
                ),
            )
            if not points:
                raise exceptions.MapillaryGPSNoiseError("GPS is too noisy")

        stationary = video_utils.is_video_stationary(
            geo.get_max_distance_from_start([(p.lat, p.lon) for p in points])
        )

        if stationary:
            raise exceptions.MapillaryStationaryVideoError("Stationary video")

        return points
