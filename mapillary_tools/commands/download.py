import inspect
from mapillary_tools.download import download


class Command:
    name = 'download'
    help = 'Helper tool : For a specified import path, download the blurred images from Mapillary.'

    def add_basic_arguments(self, parser):
        parser.add_argument("--output_folder",
                            help="Output folder for the downloaded images.", required=True)
        parser.add_argument("--user_name", help="user name", required=True)

    def add_advanced_arguments(self, parser):
        parser.add_argument(
            '--number_threads', help='Specify the number of download threads.', type=int, default=10, required=False)

    def run(self, args):

        vars_args = vars(args)
        download(**({k: v for k, v in vars_args.iteritems()
                     if k in inspect.getargspec(download).args}))

        print("Download done.")
