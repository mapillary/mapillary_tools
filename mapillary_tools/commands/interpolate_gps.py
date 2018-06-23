from mapillary_tools.interpolate_missing_gps import interpolate_missing_gps


class Command:
    name = 'interpolate_gps'
    help = "Preprocess tool : Interpolate missing gps."

    def add_basic_arguments(self, parser):
        parser.add_argument('--max_time_delta', default=1., type=float,
                            help='Maximum delta time in seconds, for a timestamp out of scope to be extrapolated.', required=False)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):

        interpolate_missing_gps(**vars(args))
