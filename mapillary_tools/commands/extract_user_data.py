
from mapillary_tools.process_user_properties import (
    add_user_arguments,
    add_organization_arguments,
    add_mapillary_arguments,
    process_user_properties)


class Command:
    name = 'extract_user_data'
    help = "Process unit tool : Extract and process user properties."

    def add_basic_arguments(self, parser):
        add_user_arguments(parser)
        add_organization_arguments(parser)

    def add_advanced_arguments(self, parser):
        add_mapillary_arguments(parser)

    def run(self, args):
        process_user_properties(**vars(args))
