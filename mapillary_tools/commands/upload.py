import inspect
from mapillary_tools.upload import (
    add_upload_arguments,
    add_dry_run_arguments,
    upload)
from mapillary_tools.post_process import post_process


class Command:
    name = 'upload'
    help = "Main tool : Upload images to Mapillary."

    def add_basic_arguments(self, parser):
        pass

    def add_advanced_arguments(self, parser):
        add_upload_arguments(parser)
        add_dry_run_arguments(parser)

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
        parser.add_argument('--save_local_mapping', help='Save the mapillary photo uuid to local file mapping in a csv.',
                            action='store_true', default=False, required=False)

    def run(self, args):

        vars_args = vars(args)

        upload(**({k: v for k, v in vars_args.iteritems()
                   if k in inspect.getargspec(upload).args}))

        post_process(**({k: v for k, v in vars_args.iteritems()
                         if k in inspect.getargspec(post_process).args}))
