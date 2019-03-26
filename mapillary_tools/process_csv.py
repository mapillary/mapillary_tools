import processing
import uploader
import os
import sys
import datetime
import process_import_meta_properties
from exif_write import ExifEdit
import csv
from tqdm import tqdm

META_DATA_TYPES = ["string", "double", "long", "date", "boolean"]

MILLISECONDS_PRECISION_CUT_OFF = 10000000000

GPS_START = datetime.datetime(1980, 1, 6)

SECS_IN_WEEK = 604800


def format_time(timestamp, time_utc=False, time_format='%Y-%m-%dT%H:%M:%SZ'):
    if time_utc:
        division = 1.0 if float(
            timestamp) < MILLISECONDS_PRECISION_CUT_OFF else 1000.0
        t_datetime = datetime.datetime.utcfromtimestamp(
            float(timestamp) / division)
    else:
        t_datetime = datetime.datetime.strptime(timestamp, time_format)
    return t_datetime


def validate_meta_data(meta_columns, meta_names, meta_types):

    if any([x for x in [meta_columns, meta_names, meta_types]]):

        # if any of the meta data arguments are passed all must be
        if any([not(x) for x in [meta_columns, meta_names, meta_types]]):
            print(
                "Error, if extracting meta data you need to specify meta_columns, meta_names and meta_types.")
            sys.exit(1)

        # get meta data column numbers
        meta_columns = meta_columns.split(",")
        try:
            meta_columns = [int(field) - 1 for field in meta_columns]
        except:
            print('Error, meta column numbers could not be extracted. Meta column numbers need to be separated with commas, example "7,9,10"')
            sys.exit(1)

        # get meta data names and types
        meta_names = meta_names.split(",")
        meta_types = meta_types.split(",")

        # exit if they are not all of same length
        if len(meta_columns) != len(meta_names) or len(meta_types) != len(meta_names):
            print(
                "Error, number of meta data column numbers, types and names must be the same.")
            sys.exit(1)

        # check if types are valid
        for meta_type in meta_types:
            if meta_type not in META_DATA_TYPES:
                print("Error, invalid meta data type, valid types are " +
                      str(META_DATA_TYPES))
                sys.exit(1)
    return meta_columns, meta_names, meta_types


def convert_from_gps_time(gps_time, gps_week=None):
    """ Convert gps time in ticks to standard time. """

    converted_gps_time = None
    gps_timestamp = float(gps_time)

    if gps_week != None:

        # image date
        converted_gps_time = GPS_START + datetime.timedelta(seconds=int(gps_week) *
                                                            SECS_IN_WEEK + gps_timestamp)

    else:
        # TAI scale with 1970-01-01 00:00:10 (TAI) epoch
        os.environ['TZ'] = 'right/UTC'

        # by definition
        gps_time_as_gps = GPS_START + \
            datetime.timedelta(seconds=gps_timestamp)

        # constant offset
        gps_time_as_tai = gps_time_as_gps + \
            datetime.timedelta(seconds=19)
        tai_epoch_as_tai = datetime.datetime(1970, 1, 1, 0, 0, 10)

        # by definition
        tai_timestamp = (gps_time_as_tai - tai_epoch_as_tai).total_seconds()

        converted_gps_time = (
            datetime.datetime.utcfromtimestamp(tai_timestamp))

    # "right" timezone is in effect
    return converted_gps_time


def get_image_index(image, file_names):

    image_index = None
    try:
        image_index = file_names.index(image)
    except:
        try:
            file_names = [os.path.basename(entry) for entry in file_names]
            image_index = file_names.index(os.path.basename(image))
        except:
            try:
                image_index = [idx for idx, file_name in enumerate(
                    file_names) if file_name in image][0]
            except:
                try:
                    image_index = [idx for idx, file_name in enumerate(
                        file_names) if ".".join(file_name.split(".")[:-1]) in image][0]
                except:
                    pass
    return image_index


def parse_csv_geotag_data(csv_data, image_index, column_indexes, convert_gps_time=False, convert_utc_time=False, time_format="%Y:%m:%d %H:%M:%S.%f"):

    timestamp = None
    lat = None
    lon = None
    heading = None
    altitude = None

    timestamp_column = column_indexes[1]
    latitude_column = column_indexes[2]
    longitude_column = column_indexes[3]
    heading_column = column_indexes[4]
    altitude_column = column_indexes[5]
    gps_week_column = column_indexes[6]

    if timestamp_column != None:
        timestamp = csv_data[timestamp_column][image_index]
        gps_week = None
        if gps_week_column != None:
            gps_week = csv_data[gps_week_column][image_index]
        timestamp = convert_from_gps_time(
            timestamp, gps_week) if convert_gps_time else format_time(timestamp, convert_utc_time, time_format)

    if latitude_column != None:
        lat = float(csv_data[latitude_column][image_index])
    if longitude_column != None:
        lon = float(csv_data[longitude_column][image_index])
    if heading_column != None:
        heading = float(csv_data[heading_column][image_index])
    if altitude_column != None:
        altitude = float(csv_data[altitude_column][image_index])

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

def add_process_csv_basic_arguments(parser):
    parser.add_argument('--csv_path',
        help='Provide the path to the csv file.',
        action='store', required=True)
    parser.add_argument('--delimiter',
        help='Delimiter between the columns.',
        action='store', default=',', required=False)
    parser.add_argument('--convert_gps_time',
        help='Convert gps time in ticks to standard time.',
        action='store_true', default=False, required=False)
    parser.add_argument('--convert_utc_time',
        help='Convert utc epoch time in seconds or milliseconds.',
        action='store_true', default=False, required=False)
    parser.add_argument('--filename_column',
        help='Specify the column number of image filename, counting from 1 on.',
        action='store', type=int, required=False)
    parser.add_argument('--timestamp_column',
        help='Specify the column number of image timestamp, counting from 1 on.',
        action='store', type=int, required=False)
    parser.add_argument('--latitude_column',
        help='Specify the column number of image latitude, counting from 1 on.',
        action='store', type=int, required=False)
    parser.add_argument('--longitude_column',
        help='Specify the column number of image longitude, counting from 1 on.',
        action='store', type=int, required=False)
    parser.add_argument('--heading_column',
        help='Specify the column number of image heading, counting from 1 on.',
        action='store', type=int, required=False)
    parser.add_argument('--altitude_column',
        help='Specify the column number of image altitude, counting from 1 on.',
        action='store', type=int, required=False)
    parser.add_argument('--gps_week_column',
        help='Specify the column number of image timestamps gps week, counting from 1 on. Used only with --convert_gps_time.',
        action='store', type=int, required=False)
    parser.add_argument('--meta_columns',
        help='Specify the column numbers containing meta data, separate numbers with commas, example "7,9,10".',
        action='store', default=None, required=False)
    parser.add_argument('--meta_names',
        help='Specify the meta data names, separate names with commas, example "meta_data_1,meta_data2,meta_data3".',
        action='store', default=None, required=False)
    parser.add_argument('--meta_types',
        help='Specify the meta data types, separate types with commas, example "string,string,long". Available types are [string, double, long, date, boolean]',
        action='store', default=None, required=False)
    parser.add_argument('--time_format',
        help='Specify the format of the date/time.',
        action='store', default='%Y:%m:%d %H:%M:%S.%f', required=False)
    parser.add_argument('--header',
        help='The csv file includes a header.',
        action='store_true', default=False, required=False)

def add_process_csv_advanced_arguments(parser):
    parser.add_argument('--keep_original',
        help='Do not overwrite original images, instead save the processed images in a new directory by adding suffix "_processed" to the import_path.',
        action='store_true', default=False, required=False)

def process_csv(import_path,
                csv_path,
                filename_column=None,
                timestamp_column=None,
                latitude_column=None,
                longitude_column=None,
                heading_column=None,
                altitude_column=None,
                gps_week_column=None,
                time_format="%Y:%m:%d %H:%M:%S.%f",
                convert_gps_time=False,
                convert_utc_time=False,
                delimiter=",",
                header=False,
                meta_columns=None,
                meta_names=None,
                meta_types=None,
                verbose=False,
                keep_original=False):

    # sanity checks
    if not import_path or not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " doesnt not exist, exiting...")
        sys.exit(1)

    if not csv_path or not os.path.isfile(csv_path):
        print("Error, csv file not provided or does not exist. Please specify a valid path to a csv file.")
        sys.exit(1)

    # get list of file to process
    process_file_list = uploader.get_total_file_list(import_path)
    if not len(process_file_list):
        print("No images found in the import path " + import_path)
        sys.exit(1)

    if gps_week_column != None and convert_gps_time == False:
        print("Error, in order to parse timestamp provided as a combination of GPS week and GPS seconds, you must specify timestamp column and flag --convert_gps_time, exiting...")
        sys.exit(1)

    if (convert_gps_time != False or convert_utc_time != False) and timestamp_column == None:
        print("Error, if specifying a flag to convert timestamp, timestamp column must be provided, exiting...")
        sys.exit(1)

    column_indexes = [filename_column, timestamp_column,
                      latitude_column, longitude_column, heading_column, altitude_column, gps_week_column]

    if any([column == 0 for column in column_indexes]):
        print("Error, csv column numbers start with 1, one of the columns specified is 0.")
        sys.exit(1)

    column_indexes = map(lambda x: x - 1 if x else None, column_indexes)

    # checks for meta arguments if any
    meta_columns, meta_names, meta_types = validate_meta_data(
        meta_columns, meta_names, meta_types)

    # open and process csv
    csv_data = read_csv(csv_path,
                        delimiter=delimiter,
                        header=header)

    # align by filename column if provided, otherwise align in order of image
    # names
    file_names = None
    if filename_column:
        file_names = csv_data[filename_column - 1]
    else:
        if verbose:
            print("Warning, filename column not provided, images will be aligned with the csv data in order of the image filenames.")

    # process each image
    for idx, image in tqdm(enumerate(process_file_list), desc="Inserting csv data in image EXIF"):

        # get image entry index
        image_index = get_image_index(image, file_names) if file_names else idx
        if image_index == None:
            print("Warning, no entry found in csv file for image " + image)
            continue

        # get required data
        timestamp, lat, lon, heading, altitude = parse_csv_geotag_data(
            csv_data, image_index, column_indexes, convert_gps_time, convert_utc_time, time_format)

        # get meta data
        meta = parse_csv_meta_data(
            csv_data, image_index, meta_columns, meta_types, meta_names)

        # insert in image EXIF
        exif_edit = ExifEdit(image)
        if timestamp:
            exif_edit.add_date_time_original(timestamp)
        if lat and lon:
            exif_edit.add_lat_lon(lat, lon)
        if heading:
            exif_edit.add_direction(heading)
        if altitude:
            exif_edit.add_altitude(altitude)
        if meta:
            exif_edit.add_image_history(meta["MAPMetaTags"])

        filename = image
        filename_keep_original = processing.processed_images_rootpath(image)

        if os.path.isfile(filename_keep_original):
            os.remove(filename_keep_original)

        if keep_original:
            if not os.path.isdir(os.path.dirname(filename_keep_original)):
                os.makedirs(os.path.dirname(filename_keep_original))
            filename = filename_keep_original

        try:
            exif_edit.write(filename=filename)
        except:
            print("Error, image EXIF could not be written back for image " + image)
            return None
