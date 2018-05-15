import os
import sys

from mapillary_tools.process_upload_params import process_upload_params


class Command:
    name = 'extract_upload_params'
    help = "Extract upload params."

    def add_arguments(self, parser):
        # general arguments
        parser.add_argument(
            'path', help='path to your photos, or in case of video, path where the photos from video sampling will be saved')
        parser.add_argument(
            '--skip_subfolders', help='Skip all subfolders and import only the images in the given directory path.', action='store_true', default=False, required=False)
        # force rerun process, will rewrite the json and update the processing
        parser.add_argument(
            '--verbose', help='print debug info', action='store_true', default=False, required=False)
        parser.add_argument(
            '--rerun', help='rerun the processing', action='store_true', required=False)

        # command specific args
        parser.add_argument("--user_name", help="user name", required=True)
        # master upload
        parser.add_argument('--master_upload', help='Process images with a master key, note: only used by Mapillary employees',
                            action='store_true', default=False, required=False)

    def run(self, args):

        # basic check for all
        import_path = os.path.abspath(args.path)
        if not os.path.isdir(import_path):
            print("Error, import directory " + import_path +
                  " doesnt not exist, exiting...")
            sys.exit()

        process_upload_params(import_path,
                              args.user_name,
                              args.master_upload,
                              args.verbose,
                              args.rerun,
                              args.skip_subfolders)
