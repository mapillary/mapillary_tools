from mapillary_tools.process_geotag_properties import add_offset_angle_argument
from mapillary_tools.process_sequence_properties import (
    add_sequence_arguments,
    process_sequence_properties)


class Command:
    name = 'extract_sequence_data'
    help = "Process unit tool : Extract and process sequence properties."

    def add_basic_arguments(self, parser):
        pass

    def add_advanced_arguments(self, parser):
        add_sequence_arguments(parser)
        add_offset_angle_argument(parser)

    def run(self, args):

        process_sequence_properties(**vars(args))
