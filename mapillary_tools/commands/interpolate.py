from mapillary_tools.interpolation import interpolation


class Command:
    name = 'interpolate'
    help = "Preprocess tool : Interpolate missing gps, identical timestamps, etc..."

    def add_basic_arguments(self, parser):
        parser.add_argument('--data', action='store',
                            choices=['missing_gps', 'identical_timestamps'],
                            help='Specify which data you want to interpolate.', required=True)
        parser.add_argument('--max_time_delta', default=1., type=float,
                            help='Maximum delta time in seconds, for an image with a timestamp out of scope to have missing gps extrapolated.', required=False)
        parser.add_argument(
            '--file_in_path', help='Input file path, in case the identical timestamps to be interpolated are in an external file.', required=False)
        parser.add_argument('--file_format',
                            help='Format of the input file, only csv supported for now.', required=False, default="csv")
        parser.add_argument('--time_column', help='Column with the timestamps, in case interpolating missing timestamps in a csv file.',
                            required=False, type=int, default=0)
        parser.add_argument(
            '--delimiter', help="Delimiter between the columns, in case interpolating missing timestamps in a csv file.", default=",", required=False)
        parser.add_argument('--time_utc', help='Is the timestamp in utc',
                            action='store_true', default=False, required=False)
        parser.add_argument('--time_format', help="Time format in a string",
                            default='%Y-%m-%dT%H:%M:%SZ', required=False)
        parser.add_argument('--header', help="Specify whether the csv file includes a header, in case interpolating missing timestamps in a csv file..",
                            default=False, required=False, action='store_true')
        parser.add_argument('--keep_original', help='Do not overwrite original file, instead save the file with interpolated times in a new file by adding suffix "_processed" to the input file.',
                            action='store_true', default=False, required=False)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):

        interpolation(**vars(args))
