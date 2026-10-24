# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import bisect
import dataclasses
import datetime
import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from .. import constants, exceptions, geo, types
from ..serializer.description import build_capture_time
from .base import GeotagImagesFromGeneric
from .geotag_images_from_exif import ImageEXIFExtractor
from .video_extractors.gpx import describe_gap, track_gaps


LOG = logging.getLogger(__name__)


def check_within_track(
    time: float,
    sorted_points: T.Sequence[geo.Point],
    gaps: T.Sequence[tuple[geo.Point, geo.Point]] = (),
) -> None:
    """
    Raise MapillaryOutsideGPXTrackError if **time** falls outside the track of
    **sorted_points**, with a tolerance of 1 ms: before its start, after its
    end, or in one of its **gaps** (see track_gaps())

    >>> track = [geo.Point(time=t, lat=0, lon=0, alt=None, angle=None) for t in (10, 20, 9000)]
    >>> check_within_track(15.0, track)
    >>> check_within_track(9000.0005, track)
    >>> check_within_track(9.5, track)
    Traceback (most recent call last):
    ...
    mapillary_tools.exceptions.MapillaryOutsideGPXTrackError: The image date time is 0.5 seconds behind the GPX start point
    >>> check_within_track(4000.0, track, track_gaps(track, 3600))
    Traceback (most recent call last):
    ...
    mapillary_tools.exceptions.MapillaryOutsideGPXTrackError: The GPX track has a gap of 2.5 hours, from 1970-01-01T00:00:20+00:00 at (0, 0) to 1970-01-01T02:30:00+00:00 at (0, 0), which the image time 1970-01-01T01:06:40+00:00 falls in
    """
    assert sorted_points, "must have at least one point"

    if time < sorted_points[0].time:
        delta = sorted_points[0].time - time
        gpx_start_time = build_capture_time(sorted_points[0].time)
        gpx_end_time = build_capture_time(sorted_points[-1].time)
        # with the tolerance of 1ms
        if 0.001 < delta:
            raise exceptions.MapillaryOutsideGPXTrackError(
                f"The image date time is {round(delta, 3)} seconds behind the GPX start point",
                image_time=build_capture_time(time),
                gpx_start_time=gpx_start_time,
                gpx_end_time=gpx_end_time,
            )

    if sorted_points[-1].time < time:
        delta = time - sorted_points[-1].time
        gpx_start_time = build_capture_time(sorted_points[0].time)
        gpx_end_time = build_capture_time(sorted_points[-1].time)
        # with the tolerance of 1ms
        if 0.001 < delta:
            raise exceptions.MapillaryOutsideGPXTrackError(
                f"The image time is {round(delta, 3)} seconds beyond the GPX end point",
                image_time=build_capture_time(time),
                gpx_start_time=gpx_start_time,
                gpx_end_time=gpx_end_time,
            )

    # The last gap that starts at or before the image
    idx = bisect.bisect_right([before.time for before, _ in gaps], time)
    if idx:
        before, after = gaps[idx - 1]
        delta = min(time - before.time, after.time - time)
        # with the tolerance of 1ms, as at the ends of the track
        if 0.001 < delta:
            captured_at = datetime.datetime.fromtimestamp(
                time, tz=datetime.timezone.utc
            ).isoformat()
            track_gap = describe_gap(before, after, before.time, after.time)
            raise exceptions.MapillaryOutsideGPXTrackError(
                f"The GPX track has {track_gap}, which the image time {captured_at} falls in",
                image_time=build_capture_time(time),
                gpx_start_time=build_capture_time(sorted_points[0].time),
                gpx_end_time=build_capture_time(sorted_points[-1].time),
            )


class GeotagImagesFromGPX(GeotagImagesFromGeneric):
    def __init__(
        self,
        points: T.Sequence[geo.Point],
        use_gpx_start_time: bool = False,
        use_image_start_time: bool = False,
        offset_time: float = 0.0,
        num_processes: int | None = None,
        # Whether an image in a gap of the track longer than
        # constants.MAX_GPX_GAP_SECONDS is outside it
        check_gaps: bool = True,
    ):
        super().__init__(num_processes=num_processes)
        self.points = points
        self.use_gpx_start_time = use_gpx_start_time
        self.use_image_start_time = use_image_start_time
        self.offset_time = offset_time
        self.check_gaps = check_gaps
        # Why the track could not be read, reported for every image instead
        self.track_error: Exception | None = None

    def _interpolate_image_metadata_along(
        self,
        image_metadata: types.ImageMetadata,
        sorted_points: T.Sequence[geo.Point],
        gaps: T.Sequence[tuple[geo.Point, geo.Point]] = (),
    ) -> types.ImageMetadata:
        check_within_track(image_metadata.time, sorted_points, gaps)

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
        if self.track_error is not None:
            return [
                types.describe_error_metadata(
                    self.track_error, image_path, filetype=types.FileType.IMAGE
                )
                for image_path in image_paths
            ]

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

        gaps = (
            track_gaps(sorted_points, constants.MAX_GPX_GAP_SECONDS)
            if self.check_gaps
            else []
        )

        for image_metadata in sorted_image_metadatas:
            try:
                final_metadatas.append(
                    self._interpolate_image_metadata_along(
                        image_metadata, sorted_points, gaps
                    )
                )
            except exceptions.MapillaryOutsideGPXTrackError as ex:
                error_metadata = types.describe_error_metadata(
                    ex, image_metadata.filename, filetype=types.FileType.IMAGE
                )
                final_metadatas.append(error_metadata)

        assert len(image_paths) == len(final_metadatas)

        return final_metadatas
