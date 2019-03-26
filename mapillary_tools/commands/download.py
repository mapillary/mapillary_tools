import sys
import inspect
from mapillary_tools.process_user_properties import add_user_arguments
from mapillary_tools.download import (
    add_download_basic_arguments,
    add_download_advanced_arguments,
    download)
from mapillary_tools.download_blurred import download as download_blurred


class Command:
    name = 'download'
    help = '''Helper tool : download the blurred images from Mapillary
either for a specified import path or by image keys.
'''

    def add_basic_arguments(self, parser):
        add_user_arguments(parser)
        add_download_basic_arguments(parser)
        parser.add_argument("--by_property",
                            help="Image reference, either UUID or KEY",
                            type=str,
                            choices=['key', 'uuid'],
                            default='uuid')
        parser.add_argument('--organization_keys',
                            help="Organizations which own the imagery")
        parser.add_argument('--start_time',
                            help="Since when to pull the images (YYYY-MM-DD)")
        parser.add_argument('--end_time',
                            help="Until when to pull the images (YYYY-MM-DD)")
        parser.add_argument('--private',
                            help="Download private/public organization images",
                            type=str,
                            choices=['true', 'false'],
                            default='true')

    def add_advanced_arguments(self, parser):
        add_download_advanced_arguments(parser)

    def run(self, args):

        vars_args = vars(args)

        if (vars_args['by_property'] == 'key'):
            if (vars_args['organization_keys'] is None):
                raise Exception('organization_keys is required when by_property=key')
            download_blurred(**({k: v for k, v in vars_args.iteritems()
                                 if k in inspect.getargspec(download_blurred).args}))
        else:
            if "import_path" not in vars_args or not vars_args["import_path"]:
                print(
                    "Error: To download images imported with mapillary_tools, you need to specify --import_path")
                sys.exit(1)
            download(**({k: v for k, v in vars_args.iteritems()
                         if k in inspect.getargspec(download).args}))

        print("Download done.")
