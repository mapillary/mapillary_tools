from mapillary_tools.process_user_properties import add_mapillary_arguments
from mapillary_tools.insert_MAPJson import insert_MAPJson


class Command:
    name = 'exif_insert'
    help = "Process unit tool : Format and insert Mapillary image description into image EXIF ImageDescription."

    def add_basic_arguments(self, parser):
        pass

    def add_advanced_arguments(self, parser):
        add_mapillary_arguments(parser)

        parser.add_argument('--skip_EXIF_insert', help='Skip inserting the extracted data into image EXIF.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--keep_original', help='Do not overwrite original images, instead save the processed images in a new directory called "processed_images" located in .mapillary in the import_path.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--overwrite_all_EXIF_tags', help='Overwrite the rest of the EXIF tags, whose values are changed during the processing. Default is False, which will result in the processed values to be inserted only in the EXIF Image Description tag.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--overwrite_EXIF_time_tag', help='Overwrite the capture time EXIF tag with the value obtained in process.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--overwrite_EXIF_gps_tag', help='Overwrite the gps EXIF tag with the value obtained in process.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--overwrite_EXIF_direction_tag', help='Overwrite the camera direction EXIF tag with the value obtained in process.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--overwrite_EXIF_orientation_tag', help='Overwrite the orientation EXIF tag with the value obtained in process.',
                            action='store_true', default=False, required=False)

    def run(self, args):

        insert_MAPJson(**vars(args))
