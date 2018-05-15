import os
import sys

from mapillary_tools.insert_MAPJson import insert_MAPJson


class Command:
    name = 'exif_insert'
    help = "Insert the Mapillary image description into the EXIF ImageDescription tag."

    def add_arguments(self, parser):
        pass

    def run(self, args):

        # basic check for all
        import_path = os.path.abspath(args.path)
        if not os.path.isdir(import_path):
            print("Error, import directory " + import_path +
                  " doesnt not exist, exiting...")
            sys.exit()

        insert_MAPJson(import_path,
                       args.master_upload,
                       args.verbose,
                       args.rerun,
                       args.skip_subfolders)
