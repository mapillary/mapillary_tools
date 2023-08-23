import logging
import typing as T
from multiprocessing import Pool
from pathlib import Path

import tqdm

import mapillary_tools.geotag.utils as video_utils

from mapillary_tools import exceptions, geo, utils
from mapillary_tools.geotag import gpmf_gps_filter
from mapillary_tools.types import (
    ErrorMetadata,
    FileType,
    MetadataOrError,
    VideoMetadata,
    VideoMetadataOrError,
)
from mapillary_tools.video_data_extraction.cli_options import CliOptions
from mapillary_tools.video_data_extraction.extractors.base_parser import BaseParser
from mapillary_tools.video_data_extraction.video_data_parser_factory import make_parsers


LOG = logging.getLogger(__name__)


class VideoDataExtractor:
    options: CliOptions

    def __init__(self, options: CliOptions) -> None:
        self.options = options

    def process(self) -> T.List[MetadataOrError]:
        paths = self.options["paths"]
        self._check_paths(paths)
        files = utils.find_videos(paths)
        self._check_sources_cardinality(files)

        num_processes = self.options["num_processes"] or None
        with Pool(processes=num_processes) as pool:
            if num_processes == 1:
                iter: T.Iterator[VideoMetadataOrError] = map(self.process_file, files)
            else:
                iter = pool.imap(self.process_file, files)

            video_metadata_or_errors = list(
                tqdm.tqdm(
                    iter,
                    desc="Extracting GPS tracks",
                    unit="videos",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                    total=len(files),
                )
            )

        return video_metadata_or_errors

    def process_file(self, file: Path) -> VideoMetadataOrError:
        parsers = make_parsers(file, self.options)
        points: T.Sequence[geo.Point] = []
        make = self.options["device_make"]
        model = self.options["device_model"]

        exc_list: T.List[T.Dict[str, Exception]] = []
        for parser in parsers:
            log_details = {
                "filename": file,
                "parser": parser.parser_label,
                "source": parser.geotag_source_path,
            }
            if not points:
                points = self._parse_points(points, parser, log_details, exc_list)
            if not model:
                model = parser.extract_model()
            if not make:
                make = parser.extract_make()

        if points:
            video_metadata = VideoMetadata(
                filename=file,
                filetype=FileType.VIDEO,
                md5sum=None,
                points=points,
                make=make,
                model=model,
            )
            video_metadata.update_md5sum()
            return video_metadata
        else:
            return ErrorMetadata(
                filename=file,
                error=exc_list[-1]["exception"]
                if len(exc_list) > 0
                else exceptions.MapillaryVideoGPSNotFoundError(
                    "No points found"
                ),  # TODO: improve what to return
                filetype=FileType.VIDEO,
            )

    def _parse_points(
        self,
        points: T.Sequence[geo.Point],
        parser: BaseParser,
        log_details: T.Dict,
        exceptions: T.List[T.Dict[str, Exception]],
    ):
        try:
            points = parser.extract_points()
        except Exception as e:
            exceptions.append({"exception": e})
            LOG.warning(
                "%(filename)s: Exception from parser %(parser)s while processing source %(source)s: %(e)s",
                {**log_details, "e": e},
            )

        LOG.debug(
            "%(filename)s: %(points)d points extracted by parser %(parser)s from file %(source)s}",
            {**log_details, "points": len(points)},
        )

        try:
            points = self._sanitize_points(points)
        except Exception as e:
            exceptions.append({"exception": e})
            points = []
            LOG.warning(
                "%(filename)s: Exception during sanitization of points by parser %(parser)s while processing source %(source)s: %(e)s",
                {**log_details, "e": e},
            )
        # TODO: Incorporate mapillary_tools/geotag/geotag_videos_from_exiftool_video.py:78

        if parser.must_rebase_times_to_zero:
            points = self._rebase_times(points)

        return points

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

        if all(isinstance(p, geo.PointWithFix) for p in points):
            points = T.cast(
                T.Sequence[geo.Point],
                gpmf_gps_filter.remove_noisy_points(
                    T.cast(T.Sequence[geo.PointWithFix], points)
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

    @staticmethod
    def _rebase_times(points: T.Sequence[geo.Point]):
        """
        Make point times start from 0
        """
        if points:
            first_timestamp = points[0].time
            for p in points:
                p.time = p.time - first_timestamp
        return points
