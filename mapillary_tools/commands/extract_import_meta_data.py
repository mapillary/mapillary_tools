
from mapillary_tools.process_import_meta_properties import (
    add_import_meta_arguments,
    process_import_meta_properties)


class Command:
    name = 'extract_import_meta_data'
    help = "Process unit tool: Extract and process import meta properties."

    def add_basic_arguments(self, parser):
        pass

    def add_advanced_arguments(self, parser):
        add_import_meta_arguments(parser)

    def run(self, args):

        process_import_meta_properties(**vars(args))
