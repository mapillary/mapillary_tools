import inspect

from .. import constants
from ..authenticate import fetch_user_items
from ..upload import upload
from .process import bold_text


class Command:
    name = "upload"
    help = "Upload processed data to Mapillary"

    @staticmethod
    def add_common_upload_options(group):
        group.add_argument(
            "--user_name",
            help="The Mapillary user account to upload to.",
            required=False,
        )
        group.add_argument(
            "--organization_key",
            help="The Mapillary organization ID to upload to.",
            default=None,
            required=False,
        )
        group.add_argument(
            "--num_upload_workers",
            help="Number of concurrent upload workers for uploading images. [default: %(default)s]",
            default=constants.MAX_IMAGE_UPLOAD_WORKERS,
            type=int,
            required=False,
        )
        group.add_argument(
            "--reupload",
            help="Re-upload data that has already been uploaded.",
            action="store_true",
            default=False,
            required=False,
        )
        group.add_argument(
            "--dry_run",
            "--dryrun",
            help="[DEVELOPMENT] Simulate upload by sending data to a local directory instead of Mapillary servers. Uses a temporary directory by default unless specified by MAPILLARY_UPLOAD_ENDPOINT environment variable.",
            action="store_true",
            default=False,
            required=False,
        )
        group.add_argument(
            "--nofinish",
            help="[DEVELOPMENT] Upload data without finalizing. The data will NOT be stored permanently or appear on the Mapillary website.",
            action="store_true",
            default=False,
            required=False,
        )
        group.add_argument(
            "--noresume",
            help="[DEVELOPMENT] Start upload from the beginning, ignoring any previously interrupted upload sessions.",
            action="store_true",
            default=False,
            required=False,
        )

    def add_basic_arguments(self, parser):
        group = parser.add_argument_group(bold_text("UPLOAD OPTIONS"))
        group.add_argument(
            "--desc_path",
            help=f'Path to the description file with processed image and video metadata (from process command). Use "-" for STDIN. [default: {{IMPORT_PATH}}/{constants.IMAGE_DESCRIPTION_FILENAME}]',
            default=None,
            required=False,
        )
        Command.add_common_upload_options(group)

    def run(self, vars_args: dict):
        if "user_items" not in vars_args:
            user_items_args = {
                k: v
                for k, v in vars_args.items()
                if k in inspect.getfullargspec(fetch_user_items).args
            }
            vars_args["user_items"] = fetch_user_items(**user_items_args)

        upload(
            **{
                k: v
                for k, v in vars_args.items()
                if k in inspect.getfullargspec(upload).args
            }
        )
