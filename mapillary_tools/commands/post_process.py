import inspect
from mapillary_tools.post_process import post_process


class Command:
    name = 'post_process'
    help = 'Post process tool : Post process for a given import path, including import summary and grouping/moving based on import status.'

    def add_basic_arguments(self, parser):

        parser.add_argument(
            '--skip_subfolders', help='Skip all subfolders and import only the images in the given directory path.', action='store_true', default=False, required=False)

    def add_advanced_arguments(self, parser):
        # video
        parser.add_argument('--video_import_path', help='Path to a video or a directory with one or more video files.',
                            action='store', default=None, required=False)

        # post process
        parser.add_argument('--summarize', help='Summarize import for given import path.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--move_all_images', help='Move all images in import_path according to import state.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--move_duplicates', help='Move images in case they were flagged as duplicates.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--move_uploaded', help='Move images according to upload state.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--move_sequences', help='Move images into sequence folders.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--save_as_json', help='Save summary or file status list in a json.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--list_file_status', help='List file status for given import path.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--push_images', help='Push images uploaded in given import path.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--split_import_path', help='Provide the path where the images should be moved to based on the import status.',
                            action='store', required=False, default=None)
        parser.add_argument('--save_local_mapping', help='Save the mapillary photo uuid to local file mapping in a csv.',
                            action='store_true', default=False, required=False)

    def run(self, args):

        vars_args = vars(args)

        post_process(**({k: v for k, v in vars_args.iteritems()
                         if k in inspect.getargspec(post_process).args}))
