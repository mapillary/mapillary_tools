
from mapillary_tools.edit_config import edit_config


class Command:
    name = 'exif_insert'
    help = "Process unit tool : Format and insert Mapillary image description into image EXIF ImageDescription."

    def add_basic_arguments(self, parser):
        parser.add_argument(
            '--rerun', help='rerun the processing', action='store_true', required=False)
        parser.add_argument(
            '--skip_subfolders', help='Skip all subfolders and import only the images in the given directory path.', action='store_true', default=False, required=False)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):

        edit_config(**vars(args))
