import os
import sys
import time

from tqdm import tqdm

from . import processing
from .error import print_error
from .exif_read import ExifRead
from . import VERSION

META_DATA_TYPES = {
    "strings": str,
    "doubles": float,
    # "longs": long,
    "longs": int,
    "dates": int,
    "booleans": bool,
}


def validate_type(tag_type, tag_value):
    if not isinstance(tag_value, META_DATA_TYPES[tag_type]):
        try:
            tag_value = META_DATA_TYPES[tag_type](tag_value)
        except:
            print_error(
                f"Error, meta value {tag_type} can not be casted to the specified type {tag_value} and will therefore not be added."
            )
            return None
    return tag_value


def add_meta_tag(mapillary_description, tag_type, key, value):
    value = validate_type(tag_type, value)
    if value is None:
        return
    meta_tag = {"key": key, "value": value}
    if "MAPMetaTags" in mapillary_description:
        if tag_type in mapillary_description["MAPMetaTags"]:
            mapillary_description["MAPMetaTags"][tag_type].append(meta_tag)
        else:
            mapillary_description["MAPMetaTags"][tag_type] = [meta_tag]
    else:
        mapillary_description["MAPMetaTags"] = {tag_type: [meta_tag]}


def parse_and_add_custom_meta_tags(mapillary_description, custom_meta_data):
    # parse entry
    meta_data_entries = custom_meta_data.split(";")
    for entry in meta_data_entries:
        # parse name, type and value
        entry_fields = entry.split(",")

        # set name, type and value
        tag_name = entry_fields[0]
        tag_type = entry_fields[1] + "s"
        tag_value = entry_fields[2]

        # insert name, type and value
        add_meta_tag(mapillary_description, tag_type, tag_name, tag_value)


def finalize_import_properties_process(
    image,
    import_path,
    orientation=None,
    device_make=None,
    device_model=None,
    GPS_accuracy=None,
    add_file_name=False,
    add_import_date=False,
    verbose=False,
    mapillary_description=None,
    custom_meta_data=None,
    camera_uuid=None,
    windows_path=False,
    exclude_import_path=False,
    exclude_path=None,
):
    if mapillary_description is None:
        mapillary_description = {}
    # always check if there are any command line arguments passed, they will
    if orientation is not None:
        mapillary_description["MAPOrientation"] = orientation
    if device_make is not None:
        mapillary_description["MAPDeviceMake"] = device_make
    if device_model is not None:
        mapillary_description["MAPDeviceModel"] = device_model
    if GPS_accuracy is not None:
        mapillary_description["MAPGPSAccuracyMeters"] = float(GPS_accuracy)
    if camera_uuid is not None:
        mapillary_description["MAPCameraUUID"] = camera_uuid
    if add_file_name:
        image_path = image
        if exclude_import_path:
            image_path = image_path.replace(import_path, "").lstrip("\\").lstrip("/")
        elif exclude_path:
            image_path = image_path.replace(exclude_path, "").lstrip("\\").lstrip("/")
        if windows_path:
            image_path = image_path.replace("/", "\\")

        mapillary_description["MAPFilename"] = image_path

    if add_import_date:
        add_meta_tag(
            mapillary_description,
            "dates",
            "import_date",
            int(round(time.time() * 1000)),
        )

    add_meta_tag(mapillary_description, "strings", "mapillary_tools_version", VERSION)

    if custom_meta_data:
        parse_and_add_custom_meta_tags(mapillary_description, custom_meta_data)

    processing.create_and_log_process(
        image, "import_meta_data_process", "success", mapillary_description, verbose
    )


def get_import_meta_properties_exif(image, verbose=False):
    import_meta_data_properties = {}
    try:
        exif = ExifRead(image)
    except:
        if verbose:
            print(
                "Warning, EXIF could not be read for image "
                + image
                + ", import properties not read."
            )
        return None
    try:
        import_meta_data_properties["MAPOrientation"] = exif.extract_orientation()
    except:
        if verbose:
            print("Warning, image orientation tag not in EXIF.")
    try:
        import_meta_data_properties["MAPDeviceMake"] = exif.extract_make()
    except:
        if verbose:
            print("Warning, camera make tag not in EXIF.")
    try:
        import_meta_data_properties["MAPDeviceModel"] = exif.extract_model()
    except:
        if verbose:
            print("Warning, camera model tag not in EXIF.")
    try:
        import_meta_data_properties["MAPMetaTags"] = eval(exif.extract_image_history())
    except:
        pass

    return import_meta_data_properties


def process_import_meta_properties(
    import_path,
    orientation=None,
    device_make=None,
    device_model=None,
    GPS_accuracy=None,
    add_file_name=False,
    add_import_date=False,
    verbose=False,
    rerun=False,
    skip_subfolders=False,
    video_import_path=None,
    custom_meta_data=None,
    camera_uuid=None,
    windows_path=False,
    exclude_import_path=False,
    exclude_path=None,
):
    # sanity check if video file is passed
    if (
        video_import_path
        and not os.path.isdir(video_import_path)
        and not os.path.isfile(video_import_path)
    ):
        print("Error, video path " + video_import_path + " does not exist, exiting...")
        sys.exit(1)

    # in case of video processing, adjust the import path
    if video_import_path:
        # set sampling path
        video_sampling_path = "mapillary_sampled_video_frames"
        video_dirname = (
            video_import_path
            if os.path.isdir(video_import_path)
            else os.path.dirname(video_import_path)
        )
        import_path = (
            os.path.join(os.path.abspath(import_path), video_sampling_path)
            if import_path
            else os.path.join(os.path.abspath(video_dirname), video_sampling_path)
        )

    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        print_error(
            "Error, import directory " + import_path + " does not exist, exiting..."
        )
        sys.exit(1)

    # get list of file to process
    process_file_list = processing.get_process_file_list(
        import_path, "import_meta_data_process", rerun, verbose, skip_subfolders
    )
    if not len(process_file_list):
        print("No images to run import meta data process")
        print(
            "If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun"
        )

    # map orientation from degrees to tags
    if orientation is not None:
        orientation = processing.format_orientation(orientation)

    # read import meta from image EXIF and finalize the import
    # properties process
    for image in tqdm(process_file_list, desc="Processing image import properties"):
        import_meta_data_properties = get_import_meta_properties_exif(image, verbose)
        finalize_import_properties_process(
            image,
            import_path,
            orientation,
            device_make,
            device_model,
            GPS_accuracy,
            add_file_name,
            add_import_date,
            verbose,
            import_meta_data_properties,
            custom_meta_data,
            camera_uuid,
            windows_path,
            exclude_import_path,
            exclude_path,
        )
    print("Sub process ended")
