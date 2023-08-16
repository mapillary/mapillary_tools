import logging
import typing as T
from multiprocessing import Pool
from pathlib import Path

import tqdm

import mapillary_tools.geotag.utils as video_utils

from mapillary_tools import exceptions, geo, types, utils
from mapillary_tools.geotag import gpmf_gps_filter
from mapillary_tools.types import FileType, MetadataOrError, VideoMetadata
from mapillary_tools.video_data_extraction.options import Options
from mapillary_tools.video_data_extraction.video_data_parser_factory import make_parsers


LOG = logging.getLogger(__name__)


class VideoDataExtractor:
    options: Options

    def __init__(self, options: Options) -> None:
        self.options = options

    @staticmethod
    def _rebase_times(points: T.Sequence[geo.Point]):
        first_timestamp = points[0].time
        for p in points:
            p.time = p.time - first_timestamp
        return points

    @staticmethod
    def _sanitize_points(points: T.Sequence[geo.Point]) -> T.Sequence[geo.Point]:
        """Deduplicates points, when possible removes noisy ones, and checks
        against stationary videos"""

        points = geo.extend_deduplicate_points(points)
        assert points, "must have at least one point"

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

    def process(self) -> T.List[MetadataOrError]:
        files = utils.find_videos(self.options["paths"])
        num_processes = self.options["num_processes"] or None

        with Pool(processes=num_processes) as pool:
            if num_processes == 1:
                iter = map(self.process_file, files)
            else:
                iter = pool.imap(self.process_file, files)

            video_metadata_or_errors = list(
                tqdm.tqdm(
                    iter,
                    desc="Extracting GPS tracks from ExifTool XML",
                    unit="videos",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                    total=len(files),
                )
            )

        return video_metadata_or_errors

    def process_file(self, file: Path) -> VideoMetadata:
        strategies = make_parsers(file, self.options)
        points = []
        make = None
        model = None

        for strategy in strategies:
            if not points:
                points = strategy.extract_points()
                if points and strategy.must_rebase_times_to_zero():
                    points = self._rebase_times(points)
            if not model:
                model = strategy.extract_model()
            if not make:
                make = strategy.extract_make()

            strategy.cleanup()

        points = self._sanitize_points(points)

        return VideoMetadata(
            filename=file,
            filetype=FileType.CAMM,
            md5sum=None,
            points=points,
            make=make,
            model=model,
        )
