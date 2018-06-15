import processing
import uploader
import os
import sys
import datetime
import process_import_meta_properties
from exif_write import ExifEdit
import csv

META_DATA_TYPES = ["string", "double", "long", "date", "boolean"]


def validate_meta_data(meta_columns, meta_names, meta_types):

    if any([x for x in [meta_columns, meta_names, meta_types]]):

        # if any of the meta data arguments are passed all must be
        if any([not(x) for x in [meta_columns, meta_names, meta_types]]):
            print(
                "Error, if extracting meta data you need to specify meta_columns, meta_names and meta_types.")
            sys.exit()

        # get meta data column numbers
        meta_columns = meta_columns.split(",")
        try:
            meta_columns = [int(field) for field in meta_columns]
        except:
            print('Error, meta column numbers could not be extracted. Meta column numbers need to be separated with commas, example "7,9,10"')
            sys.exit()

        # get meta data names and types
        meta_names = meta_names.split(",")
        meta_types = meta_types.split(",")

        # exit if they are not all of same length
        if len(meta_columns) != len(meta_names) or len(meta_types) != len(meta_names):
            print(
                "Error, number of meta data column numbers, types and names must be the same.")
            sys.exit()

        # check if types are valid
        for meta_type in meta_types:
            if meta_type not in META_DATA_TYPES:
                print("Error, invalid meta data type, valid types are " +
                      str(META_DATA_TYPES))
                sys.exit()
    return meta_columns, meta_names, meta_types


def convert_from_gps_time(gps_time):
    """ Convert gps time in ticks to standard time. """
    # TAI scale with 1970-01-01 00:00:10 (TAI) epoch
    os.environ['TZ'] = 'right/UTC'
    # time.tzset()
    gps_timestamp = float(gps_time)
    gps_epoch_as_gps = datetime.datetime(1980, 1, 6)

    # by definition
    gps_time_as_gps = gps_epoch_as_gps + \
        datetime.timedelta(seconds=gps_timestamp)

    # constant offset
    gps_time_as_tai = gps_time_as_gps + \
        datetime.timedelta(seconds=19)
    tai_epoch_as_tai = datetime.datetime(1970, 1, 1, 0, 0, 10)

    # by definition
    tai_timestamp = (gps_time_as_tai - tai_epoch_as_tai).total_seconds()

    # "right" timezone is in effect
    return (datetime.datetime.utcfromtimestamp(tai_timestamp))


def get_image_index(image, file_names):

    image_path = os.path.splitext(image.replace("\\", "/"))[0]
    image_index = None

    try:
        image_index = file_names.index(image_path)
    except:
        try:
            file_names = [os.path.basename(entry) for entry in file_names]
            image_index = file_names.index(os.path.basename(image_path))
        except:
            pass
    return image_index


def parse_csv_geotag_data(csv_data, image_index, data_fields, convert_gps_time=False, time_format="%Y:%m:%d %H:%M:%S.%f"):

    timestamp = None
    lat = None
    lon = None
    heading = None
    altitude = None

    # set column indexes
    try:
        time_column = int(data_fields[1])
        lat_column = int(data_fields[2])
        lon_column = int(data_fields[3])
    except:
        print(
            'Error, you must specify the numbers of data columns in the following order, where first four are required and last two are optional: "filename,time,lat,lon,[heading,altitude]. To specify one optional column, but skip the other, leave the field blank, example "0,1,2,3,,4".')
        sys.exit()
    try:
        heading_column = int(data_fields[4])
    except:
        pass
    try:
        altitude_column = int(data_fields[5])
    except:
        pass

    try:
        timestamp = csv_data[time_column][image_index]
        lat = float(csv_data[lat_column][image_index])
        lon = float(csv_data[lon_column][image_index])
    except:
        print(
            "Error required time, lat and lon could not be extracted.")
    try:
        timestamp = convert_from_gps_time(
            timestamp) if convert_gps_time else datetime.datetime.strptime(timestamp, time_format)
    except:
        print("Error, date/time {} could not be parsed with format {}".format(
            timestamp, time_format))
    try:
        heading = float(csv_data[heading_column][image_index])
    except:
        pass
    try:
        altitude = float(csv_data[altitude_column][image_index])
    except:
        pass
    return timestamp, lat, lon, heading, altitude


def parse_csv_meta_data(csv_data, image_index, meta_columns, meta_types, meta_names):
    meta = {}
    if meta_columns:
        for field, meta_field in enumerate(meta_columns):
            try:
                tag_type = meta_types[field] + "s"
                tag_value = csv_data[meta_field][image_index]
                tag_key = meta_names[field]
                process_import_meta_properties.add_meta_tag(
                    meta, tag_type, tag_key, tag_value)
            except:
                print("Error, meta data {} could not be extracted.".format(tag_key))
    return meta


def read_csv(csv_path, delimiter=",", header=False):
    csv_data = []

    with open(csv_path, 'r') as csvfile:
        csvreader = csv.reader(csvfile, delimiter=delimiter)
        if header:
            next(csvreader, None)

        csv_data = zip(*csvreader)

    return csv_data


def process_csv(import_path,
                csv_path,
                data_columns,
                time_format="%Y:%m:%d %H:%M:%S.%f",
                convert_gps_time=False,
                delimiter=",",
                header=False,
                meta_columns=None,
                meta_names=None,
                meta_types=None,
                verbose=False):

    # sanity checks
    if not import_path or not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " doesnt not exist, exiting...")
        sys.exit()

    if not csv_path or not os.path.isfile(csv_path):
        print("Error, csv file not provided or does not exist. Please specify a valid path to a csv file.")
        sys.exit()

    if not data_columns:
        print(
            'Error, you must specify the numbers of data columns in the folowing order, where first four are required and last two are optional: "filename,time,lat,lon,[heading,altitude]. To specify one optional column, but skip the other, leave the field blank, example "0,1,2,3,,4".')
        sys.exit()

    # get list of file to process
    process_file_list = uploader.get_total_file_list(import_path)
    if not len(process_file_list):
        print("No images found in the import path " + import_path)
        sys.exit()

    # there must be at least 4 data fields/columns
    data_fields = data_columns.split(",")
    if len(data_fields) < 4:
        print(
            'Error, you must specify the numbers of data columns in the following order, where first four are required and last two are optional: "filename,time,lat,lon,[heading,altitude]. To specify one optional column, but skip the other, leave the field blank, example "0,1,2,3,,4".')
        sys.exit()

    # checks for meta arguments if any
    meta_columns, meta_names, meta_types = validate_meta_data(
        meta_columns, meta_names, meta_types)

    # open and process csv
    csv_data = read_csv(csv_path,
                        delimiter=delimiter,
                        header=header)

    filename_column = int(data_fields[0])

    file_names = [os.path.splitext(entry.replace("\\", "/"))[0]
                  for entry in csv_data[filename_column]]

    # process each image
    for image in process_file_list:

        # get image entry index
        image_index = get_image_index(image, file_names)
        if not image_index:
            if verbose:
                print("Warning, no entry found in csv file for image " + image)
            continue

        # get required data
        timestamp, lat, lon, heading, altitude = parse_csv_geotag_data(
            csv_data, image_index, data_fields, convert_gps_time, time_format)
        if not all([x for x in [timestamp, lat, lon]]):
            print("Error, required data not extracted from csv for image " + image)

        # get meta data
        meta = parse_csv_meta_data(
            csv_data, image_index, meta_columns, meta_types, meta_names)

        # insert in image EXIF
        exif_edit = ExifEdit(image)
        exif_edit.add_date_time_original(timestamp)
        exif_edit.add_lat_lon(lat, lon)
        if heading:
            exif_edit.add_direction(heading)
        if altitude:
            exif_edit.add_altitude(altitude)
        if meta:
            exif_edit.add_image_history(meta["MAPMetaTags"])

        exif_edit.write()
