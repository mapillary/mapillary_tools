
from mapillary_tools.process_csv import process_csv


class Command:
    name = 'process_csv'
    help = "Preprocess tool : Parse csv and preprocess the images, to enable running process_and_upload."

    def add_basic_arguments(self, parser):
        parser.add_argument(
            '--csv_path', help='Provide the path to the csv file.', action='store', required=True)
        parser.add_argument('--delimiter', help='Delimiter between the columns.',
                            required=False, action="store", default=",")
        parser.add_argument("--convert_gps_time",
                            help="Convert gps time in ticks to standard time.", action="store_true", default=False, required=False)
        parser.add_argument("--convert_utc_time",
                            help="Convert utc epoch time in seconds or milliseconds.", action="store_true", default=False, required=False)
        parser.add_argument("--filename_column",
                            help='Specify the column number of image filename, counting from 1 on.', action="store", required=False, type=int)
        parser.add_argument("--timestamp_column",
                            help='Specify the column number of image timestamp, counting from 1 on.', action="store", required=False, type=int)
        parser.add_argument("--latitude_column",
                            help='Specify the column number of image latitude, counting from 1 on.', action="store", required=False, type=int)
        parser.add_argument("--longitude_column",
                            help='Specify the column number of image longitude, counting from 1 on.', action="store", required=False, type=int)
        parser.add_argument("--heading_column",
                            help='Specify the column number of image heading, counting from 1 on.', action="store", required=False, type=int)
        parser.add_argument("--altitude_column",
                            help='Specify the column number of image altitude, counting from 1 on.', action="store", required=False, type=int)
        parser.add_argument("--gps_week_column",
                            help='Specify the column number of image timestamps gps week, counting from 1 on. Used only with --convert_gps_time.', action="store", required=False, type=int)
        parser.add_argument("--meta_columns",
                            help='Specify the column numbers containing meta data, separate numbers with commas, example "7,9,10".', action="store", default=None, required=False)
        parser.add_argument("--meta_names",
                            help='Specify the meta data names, separate names with commas, example "meta_data_1,meta_data2,meta_data3".', action="store", default=None, required=False)
        parser.add_argument("--meta_types",
                            help='Specify the meta data types, separate types with commas, example "string,string,long". Available types are [string, double, long, date, boolean]', action="store", default=None, required=False)
        parser.add_argument("--time_format",
                            help='Specify the format of the date/time.', action="store", default="%Y:%m:%d %H:%M:%S.%f", required=False)
        parser.add_argument('--header', help="The csv file includes a header.",
                            default=False, required=False, action='store_true')

    def add_advanced_arguments(self, parser):
        parser.add_argument('--keep_original', help='Do not overwrite original images, instead save the processed images in a new directory by adding suffix "_processed" to the import_path.',
                            action='store_true', default=False, required=False)

    def run(self, args):

        process_csv(**vars(args))
