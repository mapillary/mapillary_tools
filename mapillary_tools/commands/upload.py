import os
import sys

from mapillary_tools.upload import upload


class Command:
    name = 'upload'
    help = "Upload images to Mapillary."

    def add_arguments(self, parser):

        # command specific args
        parser.add_argument(
            '--manual_done', help='Manually finalize the upload', action='store_true', default=False, required=False)

    def run(self, args):

        # basic check for all
        import_path = os.path.abspath(args.path)
        if not os.path.isdir(import_path):
            print("Error, import directory " + import_path +
                  " doesnt not exist, exiting...")
            sys.exit()

        upload(import_path,
               args.manual_done,
               args.skip_subfolders)
