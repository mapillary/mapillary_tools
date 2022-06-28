import inspect

from .. import constants
from ..upload import upload_multiple
from .upload import Command as UploadCommand


class Command:
    name = "upload_blackvue"
    help = "upload BlackVue videos to Mapillary"

    def add_basic_arguments(self, parser):
        parser.add_argument(
            "import_path",
            help="Path to your BlackVue videos.",
            nargs="+",
        )
        group = parser.add_argument_group(
            f"{constants.ANSI_BOLD}UPLOAD OPTIONS{constants.ANSI_RESET_ALL}"
        )
        UploadCommand.add_common_upload_options(group)

    def run(self, vars_args: dict):
        args = {
            k: v
            for k, v in vars_args.items()
            if k in inspect.getfullargspec(upload_multiple).args
        }
        args["file_type"] = "blackvue"
        upload_multiple(**args)
