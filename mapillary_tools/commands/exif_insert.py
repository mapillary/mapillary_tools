from mapillary_tools.process_user_properties import add_mapillary_arguments
from mapillary_tools.insert_MAPJson import (
    add_EXIF_insert_arguments,
    insert_MAPJson)


class Command:
    name = 'exif_insert'
    help = "Process unit tool : Format and insert Mapillary image description into image EXIF ImageDescription."

    def add_basic_arguments(self, parser):
        pass

    def add_advanced_arguments(self, parser):
        add_mapillary_arguments(parser)
        add_EXIF_insert_arguments(parser)

    def run(self, args):

        insert_MAPJson(**vars(args))
