
from mapillary_tools.upload import upload


class Command:
    name = 'upload'
    help = "Main tool : Upload images to Mapillary."

    def add_basic_arguments(self, parser):

        # command specific args
        parser.add_argument(
            '--manual_done', help='Manually finalize the upload', action='store_true', default=False, required=False)
        parser.add_argument(
            '--skip_subfolders', help='Skip all subfolders and import only the images in the given directory path.', action='store_true', default=False, required=False)

    def add_advanced_arguments(self, parser):
        parser.add_argument(
            '--number_threads', help='Specify the number of upload threads.', type=int, default=None, required=False)

    def run(self, args):

        upload(**vars(args))
