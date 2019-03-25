
from mapillary_tools.process_upload_params import process_upload_params


class Command:
    name = 'extract_upload_params'
    help = "Process unit tool : Extract and process upload parameters."

    def add_basic_arguments(self, parser):
        # user name for the import
        parser.add_argument("--user_name", help="user name", required=True)

    def add_advanced_arguments(self, parser):
        # master upload
        parser.add_argument('--master_upload', help='Process images with a master key, note: only used by Mapillary employees',
                            action='store_true', default=False, required=False)

    def run(self, args):

        process_upload_params(**vars(args))
