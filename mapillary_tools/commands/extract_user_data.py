import os
import sys

from mapillary_tools.process_user_properties import process_user_properties


class Command:
    name = 'extract_user_data'
    help = "Extract user information."

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
        # user name for the import
        parser.add_argument("--user_name", help="user name", required=True)
        # master upload
        parser.add_argument('--master_upload', help='Process images with a master key, note: only used by Mapillary employees',
                            action='store_true', default=False, required=False)
        # organization level parameters
        parser.add_argument(
            '--organization_name', help="Specify organization name", default=None, required=False)
        parser.add_argument(
            '--organization_key', help="Specify organization key", default=None, required=False)
        parser.add_argument('--private',
                            help="Specify whether the import is private", action='store_true', default=False, required=False)

    def run(self, args):

        # basic check for all
        import_path = os.path.abspath(args.path)
        if not os.path.isdir(import_path):
            print("Error, import directory " + import_path +
                  " doesnt not exist, exiting...")
            sys.exit()

        process_user_properties(import_path,
                                args.user_name,
                                args.organization_name,
                                args.organization_key,
                                args.private,
                                args.master_upload,
                                args.verbose,
                                args.rerun,
                                args.skip_subfolders)