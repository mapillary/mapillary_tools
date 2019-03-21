from mapillary_tools.interpolation import (
    add_interpolation_arguments,
    interpolation)


class Command:
    name = 'interpolate'
    help = "Preprocess tool : Interpolate missing gps, identical timestamps, etc..."

    def add_basic_arguments(self, parser):
        add_interpolation_arguments(parser)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):

        interpolation(**vars(args))
