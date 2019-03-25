from mapillary_tools.process_user_properties import (
    add_organization_arguments,
    add_mapillary_arguments)
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
            '--video_import_path', help='Path to a video or a directory with one or more video files.', action='store', required=True)
        add_organization_arguments(parser)
        parser.add_argument(
            '--sampling_distance', help="Specify distance between images to be used when sampling video", default=2, required=False)
        parser.add_argument(
            '--offset_angle', help="offset camera angle (90 for right facing, 180 for rear facing, -90 for left facing)", default=0, required=False)
        parser.add_argument(
            '--orientation', help='Specify the image orientation in degrees. ', choices=[0, 90, 180, 270], type=int, default=0, required=False)
        
    def add_advanced_arguments(self, parser):
        add_mapillary_arguments(parser)
        parser.add_argument(
            '--filter_night_time', help="Unsupported feature. Filter images taken between sunset and sunrise", action='store_true', default=False, required=False)

    def run(self, args):
        vars_args = vars(args)
        send_videos_for_processing(
            **({k: v for k, v in vars_args.iteritems() if k in inspect.getargspec(send_videos_for_processing).args}))
