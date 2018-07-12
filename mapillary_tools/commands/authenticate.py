
from mapillary_tools.edit_config import edit_config


class Command:
    name = 'authenticate'
    help = "Helper tool : (Re)run authentication."

    def add_basic_arguments(self, parser):
        parser.add_argument(
            '--config_file', help='Full path to the config file to be edited. Default is ~/.config/mapillary/config', default=None, required=False)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):

        edit_config(**vars(args))
