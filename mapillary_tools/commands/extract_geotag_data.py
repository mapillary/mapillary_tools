import os
import sys

from mapillary_tools import process_video
from mapillary_tools.process_geotag_properties import process_geotag_properties


class Command:
    name = 'extract_geotag_data'
    help = "Extract time and location data."

    def add_arguments(self, parser):

        # command specific args
        parser.add_argument('--geotag_source', help='Provide the source of date/time and gps information needed for geotagging.', action='store',
                            choices=['exif', 'gpx', 'gopro_video'], default="exif", required=False)
        parser.add_argument(
            '--geotag_source_path', help='Provide the path to the file source of date/time and gps information needed for geotagging.', action='store',
            default=None, required=False)
        parser.add_argument(
            '--local_time', help='Assume image timestamps are in your local time', action='store_true', default=False, required=False)
        parser.add_argument('--sub_second_interval',
                            help='Sub second time between shots. Used to set image times with sub-second precision',
                            type=float, default=0.0, required=False)
        parser.add_argument('--offset_time', default=0., type=float,
                            help='time offset between the camera and the gps device, in seconds.', required=False)
        parser.add_argument("--use_gps_start_time",
                            help="Use GPS trace starting time in case of derivating timestamp from filename.", action="store_true", default=False, required=False)

    def run(self, args):

        # basic check for all
        import_path = os.path.abspath(args.path)
        if not os.path.isdir(import_path):
            print("Error, import directory " + import_path +
                  " doesnt not exist, exiting...")
            sys.exit()

        process_geotag_properties(import_path,
                                  args.geotag_source,
                                  args.geotag_source_path,
                                  args.offset_time,
                                  args.offset_angle,
                                  args.local_time,
                                  args.sub_second_interval,
                                  args.use_gps_start_time,
                                  args.verbose,
                                  args.rerun,
                                  args.skip_subfolders)
