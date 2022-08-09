import typing as T
import os
import time

from . import VERSION, types, exceptions
from .types import MetaProperties


def add_meta_tag(desc: MetaProperties, tag_type: str, key: str, value_before) -> None:
    META_DATA_TYPES = {
        "strings": str,
        "doubles": float,
        "longs": int,
        "dates": int,
        "booleans": bool,
    }

    type_ = META_DATA_TYPES.get(tag_type)

    if type_ is None:
        raise exceptions.MapillaryBadParameterError(f"Invalid tag type: {tag_type}")

    try:
        value = type_(value_before)
    except (ValueError, TypeError) as ex:
        raise exceptions.MapillaryBadParameterError(
            f'Unable to parse "{key}" in the custom metatags as {tag_type}'
        ) from ex

    meta_tag = {"key": key, "value": value}
    tags = desc.setdefault("MAPMetaTags", {})
    tags.setdefault(tag_type, []).append(meta_tag)


def parse_and_add_custom_meta_tags(desc: MetaProperties, custom_meta_data: str) -> None:
    # parse entry
    meta_data_entries = custom_meta_data.split(";")
    for entry in meta_data_entries:
        # parse name, type and value
        entry_fields = entry.split(",")
        if len(entry_fields) != 3:
            raise exceptions.MapillaryBadParameterError(
                f'Unable to parse tag "{entry}" -- it must be "name,type,value"'
            )
        # set name, type and value
        tag_name = entry_fields[0]
        tag_type = entry_fields[1] + "s"
        tag_value = entry_fields[2]

        add_meta_tag(desc, tag_type, tag_name, tag_value)


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
    import_path: str,
    descs: T.List[types.ImageDescriptionFileOrError],
    orientation=None,
    device_make=None,
    device_model=None,
    GPS_accuracy=None,
    add_file_name=False,
    add_import_date=False,
    custom_meta_data=None,
    camera_uuid=None,
    windows_path=False,
    exclude_import_path=False,
    exclude_path=None,
) -> T.List[types.ImageDescriptionFileOrError]:
    for desc in types.filter_out_errors(descs):
        image = os.path.join(import_path, desc["filename"])

        if orientation is not None:
            desc["MAPOrientation"] = format_orientation(orientation)

        if device_make is not None:
            desc["MAPDeviceMake"] = device_make

        if device_model is not None:
            desc["MAPDeviceModel"] = device_model

        if GPS_accuracy is not None:
            desc["MAPGPSAccuracyMeters"] = float(GPS_accuracy)

        if camera_uuid is not None:
            desc["MAPCameraUUID"] = camera_uuid

        if add_file_name:
            image_path = image
            if exclude_import_path:
                image_path = (
                    image_path.replace(import_path, "").lstrip("\\").lstrip("/")
                )
            elif exclude_path:
                image_path = (
                    image_path.replace(exclude_path, "").lstrip("\\").lstrip("/")
                )
            if windows_path:
                image_path = image_path.replace("/", "\\")

            desc["MAPFilename"] = image_path

        if add_import_date:
            add_meta_tag(
                desc,
                "dates",
                "import_date",
                int(round(time.time() * 1000)),
            )

        add_meta_tag(desc, "strings", "mapillary_tools_version", VERSION)

        if custom_meta_data:
            parse_and_add_custom_meta_tags(desc, custom_meta_data)

    return descs
