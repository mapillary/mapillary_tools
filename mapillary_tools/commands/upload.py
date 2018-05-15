import os
import sys

from mapillary_tools.upload import upload


class Command:
    name = 'upload'
    help = "Upload images to Mapillary."

    def add_arguments(self, parser):
        # general arguments
        parser.add_argument(
            'path', help='path to your photos, or in case of video, path where the photos from video sampling will be saved')
        parser.add_argument(
            '--skip_subfolders', help='Skip all subfolders and import only the images in the given directory path.', action='store_true', default=False, required=False)

        # command specific args
        # master upload
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
