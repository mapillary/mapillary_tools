from mapillary_tools.process_user_properties import (
    add_organization_arguments,
    add_mapillary_arguments)
from mapillary_tools.edit_config import add_user_auth_arguments
from mapillary_tools.uploader import send_videos_for_processing
import inspect


class Command:
    name = 'send_videos_for_processing'
    help = "Helper tool : Send videos for processing at Mapillary."

    def add_basic_arguments(self, parser):
        add_user_auth_arguments(parser, has_jwt=False)
        parser.add_argument('--video_import_path', help='Path to a video or a directory with one or more video files.',
                            action='store', required=True)
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
