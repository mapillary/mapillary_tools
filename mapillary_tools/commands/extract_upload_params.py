import os
import sys

from mapillary_tools.process_upload_params import process_upload_params


class Command:
    name = 'extract_upload_params'
    help = "Extract upload params."

    def add_arguments(self, parser):
        pass

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
