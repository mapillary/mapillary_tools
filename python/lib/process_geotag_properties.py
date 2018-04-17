import datetime

import lib.processor as processor
import lib.uploader as uploader
from lib.exif_read import ExifRead
from lib.geo import normalize_bearing


def process_geotag_properties(full_image_list, import_path, geotag_source, geotag_source_path=None, offset_angle=0, verbose=False):
    if geotag_source == "exif":
        geotag_from_exif(full_image_list, import_path, offset_angle, verbose)
    elif geotag_source == "gpx":
        geotag_from_gpx(full_image_list, import_path,
                        geotag_source_path, offset_angle, verbose)
    elif geotag_source == "csv":
        geotag_from_csv(full_image_list, import_path,
                        geotag_source_path, offset_angle, verbose)
    else:
        geotag_from_json(full_image_list, import_path,
                         geotag_source_path, offset_angle, verbose)


def geotag_from_exif(full_image_list, import_path, offset_angle, verbose):
    for image in full_image_list:
        mapillary_description = {}
        try:
            exif = ExifRead(image)
            # required tags
            try:
                mapillary_description["MAPLongitude"], mapillary_description["MAPLatitude"] = exif.extract_lon_lat(
                )
            except:
                print("Error, " + image +
                      " image latitude or longitude tag not in EXIF. Geotagging process failed for this image, since this is required information.")
                processor.create_and_log_process(
                    image, import_path, {}, "geotag_process")
                continue
            try:
                timestamp = exif.extract_capture_time()
                mapillary_description["MAPCaptureTime"] = datetime.datetime.strftime(
                    timestamp, "%Y_%m_%d_%H_%M_%S_%f")[:-3]
            except:
                print("Error, " + image +
                      " image capture time tag not in EXIF. Geotagging process failed for this image, since this is required information.")
                processor.create_and_log_process(
                    image, import_path, {}, "geotag_process")
                continue
            # optional fields
            try:
                mapillary_description["MAPAltitude"] = exif.extract_altitude()
            except:
                if verbose:
                    print("Warning, image altitude tag not in EXIF.")
            try:
                heading = exif.extract_direction()
                if heading is None:
                    heading = 0.0
                heading = normalize_bearing(heading + offset_angle)
                # bearing of the image
                mapillary_description["MAPCompassHeading"] = {
                    "TrueHeading": heading, "MagneticHeading": heading}
            except:
                if verbose:
                    print("Warning, image direction tag not in EXIF.")
        except:
            print("Error, EXIF could not be read for image " +
                  image + ", geotagging process failed for this image since gps/time properties not read.")

        processor.create_and_log_process(
            image, import_path, mapillary_description, "geotag_process", verbose)


def geotag_from_gpx(full_image_list, import_path, geotag_source_path, verbose):
    pass


def geotag_from_csv(full_image_list, import_path, geotag_source_path, verbose):
    pass


def geotag_from_json(full_image_list, import_path, geotag_source_path, verbose):
    pass
