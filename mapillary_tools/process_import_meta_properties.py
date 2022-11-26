import logging
import typing as T

from . import types


LOG = logging.getLogger(__name__)


def format_orientation(orientation: int) -> int:
    """
    Convert orientation from clockwise degrees to exif tag

    # see http://sylvana.net/jpegcrop/exif_orientation.html
    """
    mapping: T.Mapping[int, int] = {
        0: 1,
        90: 8,
        180: 3,
        270: 6,
    }
    if orientation not in mapping:
        raise ValueError("Orientation value has to be 0, 90, 180, or 270")

    return mapping[orientation]


def process_import_meta_properties(
    metadatas: T.List[types.MetadataOrError],
    orientation=None,
    device_make=None,
    device_model=None,
    GPS_accuracy=None,
    add_file_name=False,
    add_import_date=False,
    custom_meta_data=None,
    camera_uuid=None,
) -> T.List[types.MetadataOrError]:
    if add_file_name:
        LOG.warning("The option --add_file_name is not needed any more since v0.10.0")

    if add_import_date:
        LOG.warning("The option --add_import_date is not needed any more since v0.10.0")

    if custom_meta_data:
        LOG.warning(
            "The option --custom_meta_data is not needed any more since v0.10.0"
        )

    for metadata in metadatas:
        if isinstance(metadata, types.ErrorMetadata):
            continue

        if device_make is not None:
            if isinstance(metadata, types.VideoMetadata):
                metadata.make = device_make
            else:
                metadata.MAPDeviceMake = device_make

        if device_model is not None:
            if isinstance(metadata, types.VideoMetadata):
                metadata.model = device_model
            elif isinstance(metadata, types.ImageMetadata):
                metadata.MAPDeviceModel = device_model

        if isinstance(metadata, types.ImageMetadata):
            if orientation is not None:
                metadata.MAPOrientation = format_orientation(orientation)

            if GPS_accuracy is not None:
                metadata.MAPGPSAccuracyMeters = float(GPS_accuracy)

            if camera_uuid is not None:
                metadata.MAPCameraUUID = camera_uuid

    return metadatas
