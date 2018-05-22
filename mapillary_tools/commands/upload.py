
from mapillary_tools.upload import upload


class Command:
    name = 'upload'
    help = "Main tool : Upload images to Mapillary."

    def add_basic_arguments(self, parser):

        # command specific args
        parser.add_argument(
            '--manual_done', help='Manually finalize the upload', action='store_true', default=False, required=False)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):

        upload(**vars(args))
