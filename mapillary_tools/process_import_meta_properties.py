import time
import os
import sys
import processing
import uploader
from exif_read import ExifRead


def add_meta_tag(mapillary_description,
                 type,
                 key,
                 value):
    if 'MAPMetaTags' in mapillary_description:
        if type in mapillary_description['MAPMetaTags']:
            mapillary_description['MAPMetaTags'][type].append(
                {"key": key,
                 "value": value}
            )
        else:
            mapillary_description['MAPMetaTags'][type] = [
                {"key": key,
                 "value": value}
            ]
    else:
        mapillary_description['MAPMetaTags'] = {
            type: [
                {"key": key,
                 "value": value}
            ]
        }


def finalize_import_properties_process(image,
                                       import_path,
                                       orientation=None,
                                       device_make=None,
                                       device_model=None,
                                       GPS_accuracy=None,
                                       add_file_name=False,
                                       add_import_date=False,
                                       verbose=False,
                                       mapillary_description={}):
    # always check if there are any command line arguments passed, they will
    if orientation:
        mapillary_description["MAPOrientation"] = orientation
    if device_make:
        mapillary_description['MAPDeviceMake'] = device_make
    if device_model:
        mapillary_description['MAPDeviceModel'] = device_model
    if GPS_accuracy:
        mapillary_description['MAPGPSAccuracyMeters'] = float(GPS_accuracy)

    if add_file_name:
        add_meta_tag(mapillary_description,
                     "strings",
                     "original_file_name",
                     image)

    if add_import_date:
        add_meta_tag(mapillary_description,
                     "dates",
                     "import_date",
                     int(round(time.time() * 1000)))

    add_meta_tag(mapillary_description,
                 "strings",
                 "mapillary_tools_version",
                 "0.0.2")

    processing.create_and_log_process(image,
                                      import_path,
                                      "import_meta_data_process",
                                      "success",
                                      mapillary_description,
                                      verbose)


def get_import_meta_properties_exif(image, verbose=False):
    import_meta_data_properties = {}
    try:
        exif = ExifRead(image)
    except:
        if verbose:
            print("Warning, EXIF could not be read for image " +
                  image + ", import properties not read.")
        return None
    try:
        import_meta_data_properties["MAPOrientation"] = exif.extract_orientation(
        )
    except:
        if verbose:
            print("Warning, image orientation tag not in EXIF.")
    try:
        import_meta_data_properties["MAPDeviceMake"] = exif.extract_make(
        )
    except:
        if verbose:
            print("Warning, camera make tag not in EXIF.")
    try:
        import_meta_data_properties["MAPDeviceModel"] = exif.extract_model(
        )
    except:
        if verbose:
            print("Warning, camera model tag not in EXIF.")
    try:
        import_meta_data_properties["MAPMetaTags"] = eval(exif.extract_image_history(
        ))
    except:
        pass

    return import_meta_data_properties


def process_import_meta_properties(import_path,
                                   orientation=None,
                                   device_make=None,
                                   device_model=None,
                                   GPS_accuracy=None,
                                   add_file_name=False,
                                   add_import_date=False,
                                   verbose=False,
                                   rerun=False,
                                   skip_subfolders=False):
    # basic check for all
    import_path = os.path.abspath(import_path)
    if not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " doesnt not exist, exiting...")
        sys.exit()

     # get list of file to process
    process_file_list = processing.get_process_file_list(import_path,
                                                         "import_meta_data_process",
                                                         rerun,
                                                         verbose,
                                                         skip_subfolders)
    if not len(process_file_list):
        print("No images to run import meta data process")
        print("If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun")

    # map orientation from degrees to tags
    if orientation:
        orientation = processing.format_orientation(orientation)

    # read import meta from image EXIF and finalize the import
    # properties process
    for image in process_file_list:
        import_meta_data_properties = get_import_meta_properties_exif(
            image, verbose)
        finalize_import_properties_process(image,
                                           import_path,
                                           orientation,
                                           device_make,
                                           device_model,
                                           GPS_accuracy,
                                           add_file_name,
                                           add_import_date,
                                           verbose,
                                           import_meta_data_properties)
