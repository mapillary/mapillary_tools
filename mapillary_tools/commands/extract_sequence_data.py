import os
import sys

from mapillary_tools.process_sequence_properties import process_sequence_properties


class Command:
    name = 'extract_sequence_data'
    help = "Extract sequence data."

    def add_arguments(self, parser):

        # command specific args
        parser.add_argument('--cutoff_distance', default=600., type=float,
                            help='maximum gps distance in meters within a sequence', required=False)
        parser.add_argument('--cutoff_time', default=60., type=float,
                            help='maximum time interval in seconds within a sequence', required=False)
        parser.add_argument('--interpolate_directions',
                            help='perform interploation of directions', action='store_true', required=False)
        parser.add_argument('--flag_duplicates',
                            help='flag duplicates', action='store_true', required=False)
        parser.add_argument('--duplicate_distance',
                            help='max distance for two images to be considered duplicates in meters', default=0.1, required=False)
        parser.add_argument(
            '--duplicate_angle', help='max angle for two images to be considered duplicates in degrees', default=5, required=False)

    def run(self, args):

        # basic check for all
        import_path = os.path.abspath(args.path)
        if not os.path.isdir(import_path):
            print("Error, import directory " + import_path +
                  " doesnt not exist, exiting...")
            sys.exit()

        process_sequence_properties(import_path,
                                    args.cutoff_distance,
                                    args.cutoff_time,
                                    args.interpolate_directions,
                                    args.flag_duplicates,
                                    args.duplicate_distance,
                                    args.duplicate_angle,
                                    args.verbose,
                                    args.rerun,
                                    args.skip_subfolders)
