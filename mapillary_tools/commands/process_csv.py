
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
        parser.add_argument("--data_columns",
                            help='Specify the data column numbers in the following order, where first four are required and last two are optional : "filename,time,lat,lon,[heading,altitude]". To specify one optional column, but skip the other, leave the field blank, example "0,1,2,3,,4".', action="store", required=True)
        parser.add_argument("--meta_columns",
                            help='Specify the column numbers containing meta data, separate numbers with commas, example "7,9,10".', action="store", default=None, required=False)
        parser.add_argument("--meta_names",
                            help='Specify the meta data names, separate names with commas, example "meta_data_1,meta_data2,meta_data3".', action="store", default=None, required=False)
        parser.add_argument("--meta_types",
                            help='Specify the meta data types, separate types with commas, example "string,string,long". Available types are [string, double, long, date, boolean]', action="store", default=None, required=False)
        parser.add_argument("--time_format",
                            help='Specify the format of the date/time.', action="store", default="%Y:%m:%d %H:%M:%S.%f", required=False)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):

        process_csv(**vars(args))
