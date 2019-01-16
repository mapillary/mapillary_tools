from mapillary_tools.uploader import send_videos_for_processing
import inspect


class Command:
    name = 'send_videos_for_processing'
    help = "Helper tool : Send videos for processing at Mapillary."

    def add_basic_arguments(self, parser):
        parser.add_argument(
            "--user_name", help="Mapillary user name", required=True)
        parser.add_argument(
            "--user_email", help="user email, used to create Mapillary account", default=None, required=False)
        parser.add_argument(
            "--user_password", help="password associated with the Mapillary user account", default=None, required=False)
        parser.add_argument(
            '--user_key', help='Manually specify user key', default=False, required=False)
        parser.add_argument(
            '--api_version', help='Choose which Mapillary API version to use', default=1.0, required=False)
# consider having api version as string
        parser.add_argument(
            '--skip_subfolders', help='Skip all subfolders and import only the videos in the given directory path.', action='store_true', default=False, required=False)
        parser.add_argument('--video_import_path', help='Path to a video or a directory with one or more video files.',
                            action='store', required=True)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):
        vars_args = vars(args)
        send_videos_for_processing(
            **({k: v for k, v in vars_args.iteritems() if k in inspect.getargspec(send_videos_for_processing).args}))
