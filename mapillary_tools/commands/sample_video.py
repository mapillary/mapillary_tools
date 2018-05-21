import os
import sys

from mapillary_tools import process_video


class Command:
    name = 'sample_video'
    help = "Sample video, extracting frames to be processed and uploaded to Mapillary."

    def add_arguments(self, parser):
        # video specific args
        parser.add_argument('--video_file', help='Provide the path to the video file.',
                            action='store', default=None, required=False)
        parser.add_argument('--video_sample_interval',
                            help='Time interval for sampled video frames in seconds', default=2, type=float, required=False)
        parser.add_argument("--video_duration_ratio",
                            help="Real time video duration ratio of the under or oversampled video duration.", type=float, default=1.0, required=False)
        parser.add_argument("--video_start_time", help="Video start time in epochs (milliseconds)",
                            type=int, default=None, required=False)

    def run(self, args):

        # basic check for all
        import_path = os.path.abspath(args.path)
        if not os.path.isdir(import_path):
            print("Error, import directory " + import_path +
                  " doesnt not exist, exiting...")
            sys.exit()

        # command specific checks
        video_file = os.path.abspath(
            args.video_file) if args.video_file else None
        if video_file and not os.path.isfile(video_file):
            print("Error, video file " + video_file +
                  " does not exist, exiting...")
            sys.exit()

        # sample video
        process_video.sample_video(video_file,
                                   import_path,
                                   args.video_sample_interval,
                                   args.video_start_time,
                                   args.video_duration_ratio,
                                   args.verbose)
