import dataclasses
import logging
import typing as T
from multiprocessing import Pool
from pathlib import Path

from .. import geo, types
from ..exceptions import MapillaryGPXEmptyError, MapillaryOutsideGPXTrackError
from .geotag_from_exif import GeotagFromEXIF
from .geotag_from_generic import GeotagFromGeneric


LOG = logging.getLogger(__name__)


class GeotagFromGPX(GeotagFromGeneric):
    def __init__(
        self,
        image_paths: T.Sequence[Path],
        points: T.Sequence[geo.Point],
        use_gpx_start_time: bool = False,
        use_image_start_time: bool = False,
        offset_time: float = 0.0,
    ):
        super().__init__()
        self.image_paths = image_paths
        self.points = points
        self.use_gpx_start_time = use_gpx_start_time
        self.use_image_start_time = use_image_start_time
        self.offset_time = offset_time

    @staticmethod
    def geotag_image(image_path: Path) -> types.ImageMetadataOrError:
        return GeotagFromEXIF.geotag_image(image_path, skip_lonlat_error=True)

    def geotag_multiple_images(
        self, image_paths: T.Sequence[Path]
    ) -> T.List[types.ImageMetadataOrError]:
        with Pool() as pool:
            return pool.map(self.geotag_image, image_paths)

    def _interpolate_image_metadata_along(
        self,
        image_metadata: types.ImageMetadata,
        sorted_points: T.Sequence[geo.Point],
    ) -> types.ImageMetadataOrError:
        assert sorted_points, "must have at least one point"

        if image_metadata.time < sorted_points[0].time:
            delta = sorted_points[0].time - image_metadata.time
            gpx_start_time = types.datetime_to_map_capture_time(sorted_points[0].time)
            gpx_end_time = types.datetime_to_map_capture_time(sorted_points[-1].time)
            # with the tolerance of 1ms
            if 0.001 < delta:
                exc = MapillaryOutsideGPXTrackError(
                    f"The image date time is {round(delta, 3)} seconds behind the GPX start point",
                    image_time=types.datetime_to_map_capture_time(image_metadata.time),
                    gpx_start_time=gpx_start_time,
                    gpx_end_time=gpx_end_time,
                )
                return types.describe_error_metadata(
                    exc, image_metadata.filename, filetype=types.FileType.IMAGE
                )

        if sorted_points[-1].time < image_metadata.time:
            delta = image_metadata.time - sorted_points[-1].time
            gpx_start_time = types.datetime_to_map_capture_time(sorted_points[0].time)
            gpx_end_time = types.datetime_to_map_capture_time(sorted_points[-1].time)
            # with the tolerance of 1ms
            if 0.001 < delta:
                exc = MapillaryOutsideGPXTrackError(
                    f"The image time is {round(delta, 3)} seconds beyond the GPX end point",
                    image_time=types.datetime_to_map_capture_time(image_metadata.time),
                    gpx_start_time=gpx_start_time,
                    gpx_end_time=gpx_end_time,
                )
                return types.describe_error_metadata(
                    exc, image_metadata.filename, filetype=types.FileType.IMAGE
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

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        metadatas: T.List[types.ImageMetadataOrError] = []

        if not self.points:
            exc = MapillaryGPXEmptyError("Empty GPS extracted from the geotag source")
            for image_path in self.image_paths:
                metadatas.append(
                    types.describe_error_metadata(
                        exc, image_path, filetype=types.FileType.IMAGE
                    ),
                )
            assert len(self.image_paths) == len(metadatas)
            return metadatas

        image_metadata_or_errors = self.geotag_multiple_images(self.image_paths)

        image_metadatas = []
        for metadata_or_error in image_metadata_or_errors:
            if isinstance(metadata_or_error, types.ErrorMetadata):
                metadatas.append(metadata_or_error)
            else:
                image_metadatas.append(metadata_or_error)

        if not image_metadatas:
            assert len(self.image_paths) == len(metadatas)
            return metadatas

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

        LOG.debug("Final time offset for interpolation: %s", image_time_offset)

        for image_metadata in sorted_image_metadatas:
            image_metadata.time += image_time_offset
            metadatas.append(
                self._interpolate_image_metadata_along(image_metadata, sorted_points)
            )

        assert len(self.image_paths) == len(metadatas)
        return metadatas


class GeotagFromGPXWithProgress(GeotagFromGPX):
    def __init__(
        self,
        image_paths: T.Sequence[Path],
        points: T.Sequence[geo.Point],
        use_gpx_start_time: bool = False,
        use_image_start_time: bool = False,
        offset_time: float = 0.0,
        progress_bar=None,
    ) -> None:
        super().__init__(
            image_paths,
            points,
            use_gpx_start_time=use_gpx_start_time,
            use_image_start_time=use_image_start_time,
            offset_time=offset_time,
        )
        self._progress_bar = progress_bar

    def geotag_multiple_images(
        self, image_paths: T.Sequence[Path]
    ) -> T.List[types.ImageMetadataOrError]:
        if self._progress_bar is None:
            return super().geotag_multiple_images(image_paths)

        output = []
        with Pool() as pool:
            iter = pool.imap(self.geotag_image, image_paths)
            for image_metadata_or_error in iter:
                self._progress_bar.update(1)
                output.append(image_metadata_or_error)
        return output
