import processing
import uploader
import os
import sys
from geo import interpolate_lat_lon
from exif_write import ExifEdit


def interpolate_missing_gps(import_path, max_time_delta=1, verbose=False):
    # sanity checks
    if not import_path or not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " doesnt not exist, exiting...")
        sys.exit()

    # get list of file to process
    process_file_list = uploader.get_total_file_list(import_path)
    if not len(process_file_list):
        print("No images found in the import path " + import_path)
        sys.exit()

    # get geotags from images and a list of tuples with images missing geotags
    # and their timestamp
    geotags, missing_geotags = processing.get_images_geotags(process_file_list)
    if not len(missing_geotags):
        print("No images in directory {} missing geotags, exiting...".format(import_path))
        sys.exit()
    if not len(geotags):
        print("No images in directory {} with geotags.".format(import_path))
        sys.exit()

    sys.stdout.write("Interpolating direction for {} images missing geotags.".format(
        len(missing_geotags)))

    counter = 0
    for image, timestamp in missing_geotags:
        counter += 1
        sys.stdout.write('.')
        if (counter % 100) == 0:
            print("")
        # interpolate
        try:
            lat, lon, bearing, elevation = interpolate_lat_lon(
                geotags, timestamp, max_time_delta)
        except Exception as e:
            print("Error, {}, interpolation of latitude and longitude failed for image {}".format(
                e, image))
            continue
        # insert into exif
        exif_edit = ExifEdit(image)
        if lat and lon:
            exif_edit.add_lat_lon(lat, lon)
        else:
            print("Error, lat and lon not interpolated for image {}.".format(image))
        if bearing:
            exif_edit.add_direction(bearing)
        else:
            if verbose:
                print("Warning, bearing not interpolated for image {}.".format(image))
        if elevation:
            exif_edit.add_altitude(elevation)
        else:
            if verbose:
                print("Warning, altitude not interpolated for image {}.".format(image))
        exif_edit.write()

    print("")
