
from mapillary_tools.process_user_properties import (
    add_user_arguments,
    add_mapillary_arguments)
from mapillary_tools.process_upload_params import process_upload_params


class Command:
    name = 'extract_upload_params'
    help = "Process unit tool : Extract and process upload parameters."

    def add_basic_arguments(self, parser):
        add_user_arguments(parser)

    def add_advanced_arguments(self, parser):
        add_mapillary_arguments(parser)

    def run(self, args):
        process_upload_params(**vars(args))
