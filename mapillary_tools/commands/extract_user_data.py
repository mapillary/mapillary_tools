
from mapillary_tools.process_user_properties import process_user_properties


class Command:
    name = 'extract_user_data'
    help = "Process unit tool : Extract and process user properties."

    def add_basic_arguments(self, parser):
        # user name for the import
        parser.add_argument("--user_name", help="user name", required=True)
        # organization level parameters
        parser.add_argument(
            '--organization_username', help="Specify organization user name", default=None, required=False)
        parser.add_argument(
            '--organization_key', help="Specify organization key", default=None, required=False)
        parser.add_argument('--private',
                            help="Specify whether the import is private", action='store_true', default=False, required=False)

    def add_advanced_arguments(self, parser):
        # master upload
        parser.add_argument('--master_upload', help='Process images with a master key, note: only used by Mapillary employees',
                            action='store_true', default=False, required=False)

    def run(self, args):
        process_user_properties(**vars(args))
