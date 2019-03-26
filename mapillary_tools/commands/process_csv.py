
from mapillary_tools.process_csv import (
    add_process_csv_basic_arguments,
    add_process_csv_advanced_arguments,
    process_csv)


class Command:
    name = 'process_csv'
    help = "Preprocess tool : Parse csv and preprocess the images, to enable running process_and_upload."

    def add_basic_arguments(self, parser):
        add_process_csv_basic_arguments(parser)

    def add_advanced_arguments(self, parser):
        add_process_csv_advanced_arguments(parser)

    def run(self, args):

        process_csv(**vars(args))
