import typing as T

from .geotag_from_generic import GeotagFromGeneric
from .. import types
from ..exif_read import ExifRead
from ..error import MapillaryGeoTaggingError


class GeotagFromEXIF(GeotagFromGeneric):
    def __init__(self, image_dir: str, images: T.List[str]):
        self.image_dir = image_dir
        self.images = images
        super().__init__()

    def to_description(self) -> T.List[types.FinalImageDescriptionOrError]:
        descs: T.List[types.FinalImageDescriptionOrError] = []

        for image in self.images:
            exif = ExifRead(image)

            lon, lat = exif.extract_lon_lat()
            if lat is None or lon is None:
                exc = MapillaryGeoTaggingError(
                    "Unable to extract GPS Longitude or GPS Latitude from the image"
                )
                descs.append({"error": types.describe_error(exc), "filename": image})
                continue

            timestamp = exif.extract_capture_time()
            if timestamp is None:
                exc = MapillaryGeoTaggingError(
                    "Unable to extract timestamp from the image"
                )
                descs.append({"error": types.describe_error(exc), "filename": image})
                continue

            angle = exif.extract_direction()

            desc: types.ImageDescriptionJSON = {
                "MAPLatitude": lat,
                "MAPLongitude": lon,
                "MAPCaptureTime": types.datetime_to_map_capture_time(timestamp),
                "filename": image,
            }
            if angle is not None:
                desc["MAPCompassHeading"] = {
                    "TrueHeading": angle,
                    "MagneticHeading": angle,
                }
            descs.append(desc)

        return descs
