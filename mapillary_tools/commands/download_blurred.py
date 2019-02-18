import inspect
from mapillary_tools.download_blurred import download


class Command:
    name = 'download_blurred'
    help = 'Helper tool : Download the blurred images from Mapillary for given organization'

    def add_basic_arguments(self, parser):
        parser.add_argument('--client_id',
                            help="CLIENT_ID, required",
                            required=True)
        parser.add_argument('--organization_keys',
                            help="Organization to which private imagery belongs to, required",
                            required=True)
        parser.add_argument('--start_time',
                            help="Since when to pull the images (YYYY-MM-DD), optional")
        parser.add_argument('--end_time',
                            help="Until when to pull the images (YYYY-MM-DD), optional")
        parser.add_argument("--output_folder",
                            help="Output folder for the downloaded images.",
                            required=True)
        parser.add_argument("--user_name",
                            help="user name", required=True)

    def add_advanced_arguments(self, parser):
        parser.add_argument('--number_threads',
                            help='Specify the number of download threads.',
                            type=int,
                            default=10,
                            required=False)

    def run(self, args):

        vars_args = vars(args)
        download(**({k: v for k, v in vars_args.iteritems()
                     if k in inspect.getargspec(download).args}))
