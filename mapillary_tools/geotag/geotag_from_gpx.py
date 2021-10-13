import os
import typing as T
import datetime

from .geotag_from_generic import GeotagFromGeneric
from .. import types
from ..error import MapillaryGeoTaggingError, MapillaryInterpolationError
from ..exif_read import ExifRead
from ..geo import interpolate_lat_lon, Point


class GeotagFromGPX(GeotagFromGeneric):
    def __init__(
        self, image_dir: str, images: T.List[str], points: T.List[types.GPXPoint]
    ):
        super().__init__()
        self.image_dir = image_dir
        self.images = images
        self.points = points

    def read_image_capture_time(self, image: str) -> T.Optional[datetime.datetime]:
        image_path = os.path.join(self.image_dir, image)
        return ExifRead(image_path).extract_capture_time()

    def to_description(self) -> T.List[types.FinalImageDescriptionOrError]:
        descs: T.List[types.FinalImageDescriptionOrError] = []

        if not self.points:
            exc = MapillaryInterpolationError(
                "No GPS points extracted from the geotag source"
            )
            for image in self.images:
                descs.append(
                    {
                        "error": types.describe_error(exc),
                        "filename": image,
                    }
                )
            return descs

        # need EXIF timestamps for sorting
        pairs = []
        for image in self.images:
            capture_time = self.read_image_capture_time(image)
            if capture_time is None:
                error = types.describe_error(
                    MapillaryGeoTaggingError(
                        "No capture time found from the image for interpolation"
                    )
                )
                descs.append({"error": error, "filename": image})
            else:
                pairs.append((capture_time, image))

        sorted_points = sorted(self.points, key=lambda p: p.time)
        sorted_pairs = sorted(pairs)

        if sorted_pairs:
            # assume: the ordered image timestamps are [2, 3, 4, 5]
            # the ordered gpx timestamps are [5, 6, 7, 8]
            # then the offset will be 5 - 2 = 3
            time_delta = (sorted_points[0].time - sorted_pairs[0][0]).total_seconds()
        else:
            time_delta = 0.0

        # same thing but different type
        sorted_points_for_interpolation = [
            Point(lat=p.lat, lon=p.lon, alt=p.alt, time=p.time) for p in sorted_points
        ]

        for exif_time, image in sorted_pairs:
            exif_time = exif_time + datetime.timedelta(seconds=time_delta)
            lat, lon, bearing, elevation = interpolate_lat_lon(
                sorted_points_for_interpolation, exif_time
            )
            point = types.GPXPointAngle(
                point=types.GPXPoint(
                    time=exif_time,
                    lon=lon,
                    lat=lat,
                    alt=elevation,
                ),
                angle=bearing,
            )
            descs.append(
                T.cast(
                    types.ImageDescriptionJSON, {**point.as_desc(), "filename": image}
                )
            )

        assert len(descs) == len(self.images)

        return descs
