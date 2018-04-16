import lib.processor as processor
import lib.uploader as uploader
from lib.exif_read import ExifRead


def finalize_import_properties_process(image, import_path, orientation, device_make, device_model, GPS_accuracy, add_file_name, mapillary_description={}):
    # always check if there are any command line arguments passed, they will
    # take precedence over the JSON of EXIF read ones
    if orientation:
        orientation = format_orientation(orientation)
        mapillary_description["MAPOrientation"] = orientation
    if device_make:
        mapillary_description['MAPDeviceMake'] = device_make
    if device_model:
        mapillary_description['MAPDeviceModel'] = device_model
    if GPS_accuracy:
        mapillary_description['MAPGPSAccuracyMeters'] = GPS_accuracy

    if add_file_name:
        if 'MAPMetaTags' in mapillary_description:
            if "strings" in mapillary_description['MAPMetaTags']:
                mapillary_description['MAPMetaTags']["strings"].append(
                    {"key": "original_file_name",
                     "value": image})
            else:
                mapillary_description['MAPMetaTags']["strings"] = [
                    {"key": "original_file_name",
                     "value": image}
                ]
        else:
            mapillary_description['MAPMetaTags'] = {"strings": [
                {"key": "original_file_name",
                 "value": image}
            ]}

    processor.create_and_log_process(
        image, import_path, mapillary_description, "import_meta_data_process")


def process_import_properties(full_image_list, import_path, orientation, device_make, device_model, GPS_accuracy, add_file_name, import_meta_source, import_meta_source_path):

    # map orientation from degrees to tags
    if orientation:
        orientation = processor.format_orientation(orientation)

    # if not external meta source and not image EXIF meta source, finalize the
    # import properties process
    if not import_meta_source:
        for image in full_image_list:
            finalize_import_properties_process(
                image, import_path, orientation, device_make, device_model, GPS_accuracy, add_file_name)
    else:
        if import_meta_source == "exif":
            # read import meta from image EXIF and finalize the import
            # properties process
            for image in full_image_list:
                mapillary_description = {}
                try:
                    exif = ExifRead(image)
                    try:
                        mapillary_description["MAPOrientation"] = exif.extract_orientation(
                        )
                    except:
                        print("Warning, image orientation tag not in EXIF.")
                    try:
                        mapillary_description["MAPDeviceMake"] = exif.extract_make(
                        )
                    except:
                        print("Warning, camera make tag not in EXIF.")
                    try:
                        mapillary_description["MAPDeviceModel"] = exif.extract_model(
                        )
                    except:
                        print("Warning, camera model tag not in EXIF.")
                except:
                    print("Warning, EXIF could not be read for image " +
                          image + ", import properties not read.")

                finalize_import_properties_process(
                    image, import_path, orientation, device_make, device_model, GPS_accuracy, add_file_name, mapillary_description)
        else:
            # read import meta from json and finalize the import properties
            # process
            pass
