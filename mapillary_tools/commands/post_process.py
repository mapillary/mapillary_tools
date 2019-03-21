import inspect
from mapillary_tools.post_process import (
    add_post_process_arguments,
    post_process)


class Command:
    name = 'post_process'
    help = 'Post process tool : Post process for a given import path, including import summary and grouping/moving based on import status.'

    def add_basic_arguments(self, parser):
        pass

    def add_advanced_arguments(self, parser):
        # video
        parser.add_argument('--video-import-path', '--video_import_path',
            help='Path to a video or a directory with one or more video files.',
            action='store', default=None, required=False)

        add_post_process_arguments(parser)

    def run(self, args):

        vars_args = vars(args)

        post_process(**({k: v for k, v in vars_args.iteritems()
                         if k in inspect.getargspec(post_process).args}))
