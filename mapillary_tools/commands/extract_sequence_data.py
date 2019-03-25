
from mapillary_tools.process_sequence_properties import process_sequence_properties


class Command:
    name = 'extract_sequence_data'
    help = "Process unit tool : Extract and process sequence properties."

    def add_basic_arguments(self, parser):
        pass

    def add_advanced_arguments(self, parser):
        parser.add_argument('--cutoff_distance', default=600., type=float,
                            help='maximum gps distance in meters within a sequence', required=False)
        parser.add_argument('--cutoff_time', default=60., type=float,
                            help='maximum time interval in seconds within a sequence', required=False)
        parser.add_argument('--interpolate_directions',
                            help='perform interpolation of directions', action='store_true', required=False)
        parser.add_argument('--keep_duplicates',
                            help='keep duplicates, ie do not flag duplicates for upload exclusion, but keep them to be uploaded', action='store_true', required=False, default=False)
        parser.add_argument('--duplicate_distance', default=0.1, type=float,
                            help='max distance for two images to be considered duplicates in meters', required=False)
        parser.add_argument('--duplicate_angle', default=5., type=float,
                            help='max angle for two images to be considered duplicates in degrees', required=False)
        parser.add_argument('--offset_angle', default=0., type=float,
                            help='offset camera angle (90 for right facing, 180 for rear facing, -90 for left facing)', required=False)

    def run(self, args):

        process_sequence_properties(**vars(args))
