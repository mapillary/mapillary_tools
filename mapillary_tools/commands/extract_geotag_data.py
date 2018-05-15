import os
import sys

from mapillary_tools import process_video
from mapillary_tools.process_geotag_properties import process_geotag_properties


class Command:
    name = 'extract_geotag_data'
    help = "Extract time and location data."

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
        parser.add_argument('--geotag_source', help='Provide the source of date/time and gps information needed for geotagging.', action='store',
                            choices=['exif', 'gpx', 'csv', 'json', 'gopro_video'], default="exif", required=False)
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
        parser.add_argument('--offset_angle', default=0., type=float,
                            help='offset camera angle (90 for right facing, 180 for rear facing, -90 for left facing)', required=False)
        parser.add_argument("--use_gps_start_time",
                            help="Use GPS trace starting time.", action="store_true", default=False, required=False)

        # video specific args
        parser.add_argument(
            '--video_file', help='Provide the path to the video file.', action='store', default=None, required=False)
        parser.add_argument(
            '--video_sample_interval', help='Time interval for sampled video frames in seconds', default=2, type=float, required=False)
        parser.add_argument("--video_duration_ratio",
                            help="Real time video duration ratio of the under or oversampled video duration.", type=float, default=1.0, required=False)
        parser.add_argument(
            "--video_start_time", help="Video start time in epochs (milliseconds)", type=int, default=None, required=False)

    def run(self, args):

        # basic check for all
        import_path = os.path.abspath(args.path)
        if not os.path.isdir(import_path):
            print("Error, import directory " + import_path +
                  " doesnt not exist, exiting...")
            sys.exit()

        timestamp_from_filename = False
        # set video args
        video_duration = None
        if args.video_file:
            video_duration = process_video.get_video_duration(args.video_file)
            timestamp_from_filename = True

        process_geotag_properties(import_path,
                                  args.geotag_source,
                                  args.geotag_source_path,
                                  args.offset_time,
                                  args.offset_angle,
                                  args.local_time,
                                  args.sub_second_interval,
                                  timestamp_from_filename,
                                  args.use_gps_start_time,
                                  args.verbose,
                                  args.rerun,
                                  args.skip_subfolders,
                                  args.video_start_time,
                                  video_duration,
                                  args.video_duration_ratio,
                                  args.video_sample_interval)
