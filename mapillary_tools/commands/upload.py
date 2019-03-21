import inspect
from mapillary_tools.upload import (
    add_upload_arguments,
    add_dry_run_arguments,
    upload)
from mapillary_tools.post_process import (
    add_post_process_arguments,
    post_process)


class Command:
    name = 'upload'
    help = "Main tool : Upload images to Mapillary."

    def add_basic_arguments(self, parser):
        pass

    def add_advanced_arguments(self, parser):
        add_upload_arguments(parser)
        add_dry_run_arguments(parser)
        add_post_process_arguments(parser)

    def run(self, args):

        vars_args = vars(args)

        upload(**({k: v for k, v in vars_args.iteritems()
                   if k in inspect.getargspec(upload).args}))

        post_process(**({k: v for k, v in vars_args.iteritems()
                         if k in inspect.getargspec(post_process).args}))
