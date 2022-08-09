import logging
import os
import typing as T

from tqdm import tqdm

from .geotag_from_generic import GeotagFromGeneric
from .. import types
from ..exif_read import ExifRead
from ..exceptions import MapillaryGeoTaggingError

LOG = logging.getLogger(__name__)


class GeotagFromEXIF(GeotagFromGeneric):
    def __init__(self, image_dir: str, images: T.List[str]):
        self.image_dir = image_dir
        self.images = images
        super().__init__()

    def to_description(self) -> T.List[types.ImageDescriptionFileOrError]:
        descs: T.List[types.ImageDescriptionFileOrError] = []

        for image in tqdm(
            self.images,
            desc=f"Processing",
            unit="images",
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        ):
            image_path = os.path.join(self.image_dir, image)

            try:
                exif = ExifRead(image_path)
            except Exception as exc0:
                LOG.warning(
                    "Unknown error reading EXIF from image %s",
                    image_path,
                    exc_info=True,
                )
                descs.append({"error": types.describe_error(exc0), "filename": image})
                continue

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

            desc: types.ImageDescriptionFile = {
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

            altitude = exif.extract_altitude()
            if altitude is not None:
                desc["MAPAltitude"] = altitude

            desc["MAPOrientation"] = exif.extract_orientation()

            make = exif.extract_make()
            if make is not None:
                desc["MAPDeviceMake"] = make

            model = exif.extract_model()
            if model is not None:
                desc["MAPDeviceModel"] = model

            descs.append(desc)

        return descs
