#!/usr/bin/env python

import os
import sys
import datetime

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


def eval_frac(value):
    if value.den == 0:
        return -1.0
    return float(value.num) / float(value.den)


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


def format_time(time_string):
    '''
    Format time string with invalid time elements in hours/minutes/seconds
    Format for the timestring needs to be "%Y_%m_%d_%H_%M_%S"

    e.g. 2014_03_31_24_10_11 => 2014_04_01_00_10_11
    '''
    data = time_string.split("_")
    hours, minutes, seconds = int(data[3]), int(data[4]), int(data[5])
    date = datetime.datetime.strptime("_".join(data[:3]), "%Y_%m_%d")
    subsec = 0
    if len(data) == 7:
        subsec = float(data[6]) / 10**len(data[6])
    date_time = date + \
        datetime.timedelta(hours=hours, minutes=minutes,
                           seconds=seconds + subsec)
    return date_time


def format_orientation(orientation):
    '''
    Convert orientation from clockwise degrees to exif tag

    # see http://sylvana.net/jpegcrop/exif_orientation.html
    '''
    mapping = {
        0: 1,
        90: 6,
        180: 3,
        270: 8,
    }
    if orientation not in mapping:
        raise ValueError("Orientation value has to be 0, 90, 180, or 270")

    return mapping[orientation]


def gps_to_decimal(values, reference):
    sign = 1 if reference in 'NE' else -1
    degrees = eval_frac(values[0])
    minutes = eval_frac(values[1])
    seconds = eval_frac(values[2])
    return sign * (degrees + minutes / 60 + seconds / 3600)


def get_float_tag(tags, key):
    if key in tags:
        return float(tags[key].values[0])
    else:
        return None


def get_frac_tag(tags, key):
    if key in tags:
        return eval_frac(tags[key].values[0])
    else:
        return None


def extract_exif_from_file(fileobj):
    if isinstance(fileobj, (str, unicode)):
        with open(fileobj) as f:
            exif_data = EXIF(f)
    else:
        exif_data = EXIF(fileobj)

    d = exif_data.extract_exif()
    return d


def required_fields():
    return exif_gps_fields() + exif_datetime_fields()


def verify_exif(filename):
    '''
    Check that image file has the required EXIF fields.
    Incompatible files will be ignored server side.
    '''
    # required tags in IFD name convention
    required_exif = required_fields()
    exif = EXIF(filename)
    required_exif_exist = exif.fields_exist(required_exif)
    return required_exif_exist


def verify_mapillary_tag(filename):
    '''
    Check that image file has the required Mapillary tag
    '''
    return EXIF(filename).mapillary_tag_exists()


def is_image(filename):
    return filename.lower().endswith(('jpg', 'jpeg', 'png', 'tif', 'tiff', 'pgm', 'pnm', 'gif'))
