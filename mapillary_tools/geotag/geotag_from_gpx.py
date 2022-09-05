import logging
import typing as T
from pathlib import Path

from .. import geo, types
from ..exceptions import (
    MapillaryGeoTaggingError,
    MapillaryGPXEmptyError,
    MapillaryOutsideGPXTrackError,
)
from ..exif_read import ExifRead

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

    def read_image_time(self, image_path: Path) -> T.Optional[float]:
        image_time = ExifRead(str(image_path)).extract_capture_time()
        if image_time is None:
            return None
        return geo.as_unix_time(image_time)

    def to_description(self) -> T.List[types.ImageDescriptionFileOrError]:
        descs: T.List[types.ImageDescriptionFileOrError] = []

        if not self.image_paths:
            assert len(self.image_paths) == len(descs)
            return descs

        if not self.points:
            exc = MapillaryGPXEmptyError("Empty GPS extracted from the geotag source")
            for image_path in self.image_paths:
                descs.append(
                    types.describe_error(exc, str(image_path)),
                )
            assert len(self.image_paths) == len(descs)
            return descs

        # pairing the time and the image for sorting
        image_pairs = []
        for image_path in self.image_paths:
            try:
                image_time = self.read_image_time(image_path)
            except Exception as exc:
                descs.append(
                    types.describe_error(exc, str(image_path)),
                )
                continue

            if image_time is None:
                descs.append(
                    types.describe_error(
                        MapillaryGeoTaggingError(
                            "No data time found from the image EXIF for interpolation"
                        ),
                        str(image_path),
                    )
                )
            else:
                image_pairs.append((image_time, image_path))

        if not image_pairs:
            assert len(self.image_paths) == len(descs)
            return descs

        sorted_points = sorted(self.points)
        sorted_images = sorted(image_pairs)

        first_image_time, _ = sorted_images[0]

        if self.use_image_start_time:
            # point time must be delta here
            sorted_points = [
                geo.Point(
                    time=first_image_time + p.time,
                    lat=p.lat,
                    lon=p.lon,
                    alt=p.alt,
                    angle=p.angle,
                )
                for p in sorted_points
            ]

        image_time_offset = self.offset_time

        if self.use_gpx_start_time:
            if sorted_images and sorted_points:
                # assume: the ordered image times are [2, 3, 4, 5]
                # the ordered gpx times are [5, 6, 7, 8]
                # then the offset will be 5 - 2 = 3
                time_delta = sorted_points[0].time - first_image_time
                LOG.debug("GPX start time delta: %s", time_delta)
                image_time_offset += time_delta

        LOG.debug("Final time offset for interpolation: %s", image_time_offset)

        for image_time, image_path in sorted_images:
            image_time = image_time + image_time_offset

            if image_time < sorted_points[0].time:
                delta = sorted_points[0].time - image_time
                # with the tolerance of 1ms
                if 0.001 < delta:
                    exc2 = MapillaryOutsideGPXTrackError(
                        f"The image date time is {round(delta, 3)} seconds behind the GPX start point",
                        image_time=types.datetime_to_map_capture_time(image_time),
                        gpx_start_time=types.datetime_to_map_capture_time(
                            sorted_points[0].time
                        ),
                        gpx_end_time=types.datetime_to_map_capture_time(
                            sorted_points[-1].time
                        ),
                    )
                    descs.append(types.describe_error(exc2, str(image_path)))
                    continue

            if sorted_points[-1].time < image_time:
                delta = image_time - sorted_points[-1].time
                # with the tolerance of 1ms
                if 0.001 < delta:
                    exc2 = MapillaryOutsideGPXTrackError(
                        f"The image time is {round(delta, 3)} seconds beyond the GPX end point",
                        image_time=types.datetime_to_map_capture_time(image_time),
                        gpx_start_time=types.datetime_to_map_capture_time(
                            sorted_points[0].time
                        ),
                        gpx_end_time=types.datetime_to_map_capture_time(
                            sorted_points[-1].time
                        ),
                    )
                    descs.append(
                        types.describe_error(exc2, str(image_path)),
                    )
                    continue

            interpolated = geo.interpolate(sorted_points, image_time)

            descs.append(
                T.cast(
                    types.ImageDescriptionFile,
                    {**types.as_desc(interpolated), "filename": str(image_path)},
                )
            )

        assert len(self.image_paths) == len(descs)
        return descs


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

    def read_image_time(self, image_path: Path) -> T.Optional[float]:
        try:
            image_time = super().read_image_time(image_path)
        finally:
            if self._progress_bar:
                self._progress_bar.update(1)
        return image_time
