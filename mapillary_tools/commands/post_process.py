import inspect
from mapillary_tools.post_process import post_process


class Command:
    name = 'post_process'
    help = 'Advanced tool : Post process for a given import path.'

    def add_basic_arguments(self, parser):

        parser.add_argument(
            '--skip_subfolders', help='Skip all subfolders and import only the images in the given directory path.', action='store_true', default=False, required=False)

    def add_advanced_arguments(self, parser):
        # video file
        parser.add_argument('--video_file', help='Provide the path to a video file or a directory containing a set of Blackvue video files.',
                            action='store', required=False, default=None)

        # post process
        parser.add_argument('--summarize', help='Summarize import for given import path.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--move_images', help='Move images corresponding to sequence uuid, duplicate flag and upload status.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--save_as_json', help='Save summary or file status list in a json.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--list_file_status', help='List file status for given import path.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--push_images', help='Push images uploaded in given import path.',
                            action='store_true', default=False, required=False)

    def run(self, args):

        vars_args = vars(args)

        post_process(**({k: v for k, v in vars_args.iteritems()
                         if k in inspect.getargspec(post_process).args}))
