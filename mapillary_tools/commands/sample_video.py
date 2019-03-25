
from mapillary_tools.process_video import sample_video


class Command:
    name = 'sample_video'
    help = "Main tool : Sample video into images."

    def add_basic_arguments(self, parser):
        # video specific args
        parser.add_argument('--video_import_path', help='Path to a video or directory with one or more video files.',
                            action='store', required=True)
        parser.add_argument('--video_sample_interval',
                            help='Time interval for sampled video frames in seconds', default=2, type=float, required=False)
        parser.add_argument("--video_duration_ratio",
                            help="Real time video duration ratio of the under or oversampled video duration.", type=float, default=1.0, required=False)
        parser.add_argument("--video_start_time", help="Video start time in epochs (milliseconds)",
                            type=int, default=None, required=False)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):

        # sample video
        sample_video(**vars(args))
