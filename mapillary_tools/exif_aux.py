from exif_read import ExifRead
import os
import processing


def exif_gps_fields():
    '''
    GPS fields in EXIF
    '''
    return [
        ["GPS GPSLongitude", "EXIF GPS GPSLongitude"],
        ["GPS GPSLatitude", "EXIF GPS GPSLatitude"]
    ]


def exif_datetime_fields():
    '''
    Date time fields in EXIF
    '''
    return [["EXIF DateTimeOriginal",
             "Image DateTimeOriginal",
             "EXIF DateTimeDigitized",
             "Image DateTimeDigitized",
             "EXIF DateTime",
             "Image DateTime",
             "GPS GPSDate",
             "EXIF GPS GPSDate",
             "EXIF DateTimeModified"]]


def required_fields():
    return exif_gps_fields() + exif_datetime_fields()


def verify_exif(filename):
    '''
    Check that image file has the required EXIF fields.
    Incompatible files will be ignored server side.
    '''
    # required tags in IFD name convention
    required_exif = required_fields()
    exif = ExifRead(filename)
    required_exif_exist = exif.fields_exist(required_exif)
    return required_exif_exist


def verify_mapillary_tag(filepath):
    filepath_keep_original = processing.processed_images_rootpath(filepath)
    if os.path.isfile(filepath_keep_original):
        filepath = filepath_keep_original
    '''
    Check that image file has the required Mapillary tag
    '''
    return ExifRead(filepath).mapillary_tag_exists()
