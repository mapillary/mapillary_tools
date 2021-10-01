import inspect

from ..post_process import post_process


class Command:
    name = "post_process"
    help = "post process for a given import path, including import summary and grouping/moving based on import status"

    def add_basic_arguments(self, parser):
        parser.add_argument(
            "--skip_subfolders",
            help="Skip all subfolders and import only the images in the given directory path.",
            action="store_true",
            default=False,
            required=False,
        )

    def run(self, vars_args: dict):
        post_process(
            **(
                {
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(post_process).args
                }
            )
        )
