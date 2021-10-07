import os
import time

from tqdm import tqdm

from . import image_log
from . import processing, VERSION
from .exif_read import ExifRead
from .types import MetaProperties


META_DATA_TYPES = {
    "strings": str,
    "doubles": float,
    "longs": int,
    "dates": int,
    "booleans": bool,
}


def add_meta_tag(desc: MetaProperties, tag_type: str, key: str, value_before) -> None:
    type_ = META_DATA_TYPES.get(tag_type)

    if type_ is None:
        raise RuntimeError(f"Invalid tag type: {tag_type}")

    try:
        value = type_(value_before)
    except (ValueError, TypeError) as ex:
        raise RuntimeError(
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
            raise RuntimeError(
                f'Unable to parse tag "{entry}" -- it must be "name,type,value"'
            )
        # set name, type and value
        tag_name = entry_fields[0]
        tag_type = entry_fields[1] + "s"
        tag_value = entry_fields[2]

        add_meta_tag(desc, tag_type, tag_name, tag_value)


def finalize_import_properties_process(
    image: str,
    desc: MetaProperties,
    import_path: str,
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
):
    # always check if there are any command line arguments passed, they will
    if orientation is not None:
        desc["MAPOrientation"] = orientation
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
            image_path = image_path.replace(import_path, "").lstrip("\\").lstrip("/")
        elif exclude_path:
            image_path = image_path.replace(exclude_path, "").lstrip("\\").lstrip("/")
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

    return desc


def get_import_meta_properties_exif(image: str) -> MetaProperties:
    import_meta_data_properties: MetaProperties = {}
    # FIXME: might throw error here
    exif = ExifRead(image)
    import_meta_data_properties["MAPOrientation"] = exif.extract_orientation()
    import_meta_data_properties["MAPDeviceMake"] = exif.extract_make()
    import_meta_data_properties["MAPDeviceModel"] = exif.extract_model()
    import_meta_data_properties["MAPMetaTags"] = eval(exif.extract_image_history())

    return import_meta_data_properties


def process_import_meta_properties(
    import_path,
    orientation=None,
    device_make=None,
    device_model=None,
    GPS_accuracy=None,
    add_file_name=False,
    add_import_date=False,
    skip_subfolders=False,
    custom_meta_data=None,
    camera_uuid=None,
    windows_path=False,
    exclude_import_path=False,
    exclude_path=None,
) -> None:
    if not import_path or not os.path.isdir(import_path):
        raise RuntimeError(f"Image directory {import_path} does not exist")

    process_file_list = image_log.get_total_file_list(
        import_path,
        skip_subfolders=skip_subfolders,
    )

    if not process_file_list:
        return

    if orientation is not None:
        orientation = processing.format_orientation(orientation)

    for image in tqdm(
        process_file_list, unit="files", desc="Processing import meta properties"
    ):
        import_meta_data_properties = get_import_meta_properties_exif(image)
        desc = finalize_import_properties_process(
            image,
            import_meta_data_properties,
            import_path,
            orientation,
            device_make,
            device_model,
            GPS_accuracy,
            add_file_name,
            add_import_date,
            custom_meta_data,
            camera_uuid,
            windows_path,
            exclude_import_path,
            exclude_path,
        )
        image_log.log_in_memory(image, "import_meta_data_process", desc)
