import inspect
from mapillary_tools.download import download
from mapillary_tools.download_blurred import download as download_blurred


class Command:
    name = 'download'
    help = '''Helper tool : download the blurred images from Mapillary
either for a specified import path or by image keys.
'''

    def add_basic_arguments(self, parser):
        parser.add_argument("--output_folder",
                            help="Output folder for the downloaded images.",
                            required=True)
        parser.add_argument("--user_name",
                            help="user name",
                            required=True)
        parser.add_argument("--by",
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

    def add_advanced_arguments(self, parser):
        parser.add_argument(
            '--number_threads',
            help='Specify the number of download threads.',
            type=int,
            default=10,
            required=False)

    def run(self, args):

        vars_args = vars(args)

        if (vars_args['by'] == 'key'):
            if (vars_args['organization_keys'] is None):
                raise Exception('organization_keys is required when by=key')
            download_blurred(**({k: v for k, v in vars_args.iteritems()
                                 if k in inspect.getargspec(download_blurred).args}))
        else:
            download(**({k: v for k, v in vars_args.iteritems()
                         if k in inspect.getargspec(download).args}))

        print("Download done.")
