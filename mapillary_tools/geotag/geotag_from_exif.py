import logging
import typing as T
from pathlib import Path

from tqdm import tqdm

from .. import types
from ..exceptions import MapillaryGeoTaggingError
from ..exif_read import ExifRead

from .geotag_from_generic import GeotagFromGeneric

LOG = logging.getLogger(__name__)


class GeotagFromEXIF(GeotagFromGeneric):
    def __init__(self, images: T.Sequence[Path]):
        self.images = images
        super().__init__()

    def to_description(self) -> T.List[types.ImageDescriptionFileOrError]:
        descs: T.List[types.ImageDescriptionFileOrError] = []

        image: Path
        for image in tqdm(
            self.images,
            desc=f"Processing",
            unit="images",
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        ):
            try:
                exif = ExifRead(str(image))
            except Exception as exc0:
                LOG.warning(
                    "Unknown error reading EXIF from image %s",
                    image,
                    exc_info=True,
                )
                descs.append(types.describe_error(exc0, str(image)))
                continue

            lon, lat = exif.extract_lon_lat()
            if lat is None or lon is None:
                exc = MapillaryGeoTaggingError(
                    "Unable to extract GPS Longitude or GPS Latitude from the image"
                )
                descs.append(types.describe_error(exc, str(image)))
                continue

            timestamp = exif.extract_capture_time()
            if timestamp is None:
                exc = MapillaryGeoTaggingError(
                    "Unable to extract timestamp from the image"
                )
                descs.append(types.describe_error(exc, str(image)))
                continue

            angle = exif.extract_direction()

            desc: types.ImageDescriptionFile = {
                "MAPLatitude": lat,
                "MAPLongitude": lon,
                "MAPCaptureTime": types.datetime_to_map_capture_time(timestamp),
                "filename": str(image),
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
