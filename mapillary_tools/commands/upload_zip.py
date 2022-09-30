import inspect
from pathlib import Path

from .. import constants, utils

from ..upload import upload
from .upload import Command as UploadCommand


class Command:
    name = "upload_zip"
    help = "upload ZIP files to Mapillary"

    def add_basic_arguments(self, parser):
        parser.add_argument(
            "import_path",
            help="Path to your ZIP files.",
            nargs="+",
            type=Path,
        )
        group = parser.add_argument_group(
            f"{constants.ANSI_BOLD}UPLOAD OPTIONS{constants.ANSI_RESET_ALL}"
        )
        UploadCommand.add_common_upload_options(group)

    def run(self, vars_args: dict):
        args = {
            k: v
            for k, v in vars_args.items()
            if k in inspect.getfullargspec(upload).args
        }
        upload(
            **args,
            file_types={utils.FileType.ZIP},
        )
