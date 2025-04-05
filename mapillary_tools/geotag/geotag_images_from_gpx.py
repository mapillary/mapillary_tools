from __future__ import annotations

import dataclasses
import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from .. import exceptions, geo, types
from .base import GeotagImagesFromGeneric
from .geotag_images_from_exif import ImageEXIFExtractor


LOG = logging.getLogger(__name__)


class GeotagImagesFromGPX(GeotagImagesFromGeneric):
    def __init__(
        self,
        points: T.Sequence[geo.Point],
        use_gpx_start_time: bool = False,
        use_image_start_time: bool = False,
        offset_time: float = 0.0,
        num_processes: int | None = None,
    ):
        super().__init__(num_processes=num_processes)
        self.points = points
        self.use_gpx_start_time = use_gpx_start_time
        self.use_image_start_time = use_image_start_time
        self.offset_time = offset_time

    def _interpolate_image_metadata_along(
        self,
        image_metadata: types.ImageMetadata,
        sorted_points: T.Sequence[geo.Point],
    ) -> types.ImageMetadata:
        assert sorted_points, "must have at least one point"

        if image_metadata.time < sorted_points[0].time:
            delta = sorted_points[0].time - image_metadata.time
            gpx_start_time = types.datetime_to_map_capture_time(sorted_points[0].time)
            gpx_end_time = types.datetime_to_map_capture_time(sorted_points[-1].time)
            # with the tolerance of 1ms
            if 0.001 < delta:
                raise exceptions.MapillaryOutsideGPXTrackError(
                    f"The image date time is {round(delta, 3)} seconds behind the GPX start point",
                    image_time=types.datetime_to_map_capture_time(image_metadata.time),
                    gpx_start_time=gpx_start_time,
                    gpx_end_time=gpx_end_time,
                )

        if sorted_points[-1].time < image_metadata.time:
            delta = image_metadata.time - sorted_points[-1].time
            gpx_start_time = types.datetime_to_map_capture_time(sorted_points[0].time)
            gpx_end_time = types.datetime_to_map_capture_time(sorted_points[-1].time)
            # with the tolerance of 1ms
            if 0.001 < delta:
                raise exceptions.MapillaryOutsideGPXTrackError(
                    f"The image time is {round(delta, 3)} seconds beyond the GPX end point",
                    image_time=types.datetime_to_map_capture_time(image_metadata.time),
                    gpx_start_time=gpx_start_time,
                    gpx_end_time=gpx_end_time,
                )

        interpolated = geo.interpolate(sorted_points, image_metadata.time)

        return dataclasses.replace(
            image_metadata,
            lat=interpolated.lat,
            lon=interpolated.lon,
            alt=interpolated.alt,
            angle=interpolated.angle,
            time=interpolated.time,
        )

    @override
    def _generate_image_extractors(
        self, image_paths: T.Sequence[Path]
    ) -> T.Sequence[ImageEXIFExtractor]:
        return [
            ImageEXIFExtractor(path, skip_lonlat_error=True) for path in image_paths
        ]

    @override
    def to_description(
        self, image_paths: T.Sequence[Path]
    ) -> list[types.ImageMetadataOrError]:
        final_metadatas: list[types.ImageMetadataOrError] = []

        image_metadata_or_errors = super().to_description(image_paths)

        image_metadatas, error_metadatas = types.separate_errors(
            image_metadata_or_errors
        )
        final_metadatas.extend(error_metadatas)

        if not image_metadatas:
            assert len(image_paths) == len(final_metadatas)
            return final_metadatas

        # Do not use point itself for comparison because point.angle or point.alt could be None
        # when you compare nonnull value with None, it will throw
        sorted_points = sorted(self.points, key=lambda point: point.time)
        sorted_image_metadatas = sorted(image_metadatas, key=lambda m: m.sort_key())

        if self.use_image_start_time:
            # assume the image timestamps are [10010, 10020, 10030, 10040]
            # the ordered gpx timestamps are [5, 6, 7, 8, 9]
            # and NOTE: they they be used as timedelta instead of absolute timestamps
            # after the shifting, the gpx timestamps will be [10015, 10016, 10017, 10018, 10019]
            sorted_points = [
                geo.Point(
                    time=sorted_image_metadatas[0].time + p.time,
                    lat=p.lat,
                    lon=p.lon,
                    alt=p.alt,
                    angle=p.angle,
                )
                for p in sorted_points
            ]

        image_time_offset = self.offset_time

        if self.use_gpx_start_time:
            if sorted_image_metadatas and sorted_points:
                # assume the image timestamps are [1002, 1004, 1008, 1010]
                # the ordered gpx timestamps are [1005, 1006, 1007, 1008, 1009]
                # then the offset will be 5 - 2 = 3
                # after the shifting, the image timestamps will be [1005, 1007, 1011, 1013]
                time_delta = sorted_points[0].time - sorted_image_metadatas[0].time
                LOG.debug("GPX start time delta: %s", time_delta)
                image_time_offset += time_delta

        if image_time_offset:
            LOG.debug("Final time offset for interpolation: %s", image_time_offset)
            for image_metadata in sorted_image_metadatas:
                # TODO: this time modification seems to affect final capture times
                image_metadata.time += image_time_offset

        for image_metadata in sorted_image_metadatas:
            try:
                final_metadatas.append(
                    self._interpolate_image_metadata_along(
                        image_metadata, sorted_points
                    )
                )
            except exceptions.MapillaryOutsideGPXTrackError as ex:
                error_metadata = types.describe_error_metadata(
                    ex, image_metadata.filename, filetype=types.FileType.IMAGE
                )
                final_metadatas.append(error_metadata)

        assert len(image_paths) == len(final_metadatas)

        return final_metadatas
