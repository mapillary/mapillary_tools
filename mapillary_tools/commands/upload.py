import inspect

from ..upload import upload_multiple


class Command:
    name = "upload"
    help = "upload images to Mapillary"

    def add_basic_arguments(self, parser):
        group = parser.add_argument_group("upload options")
        group.add_argument(
            "--user_name", help="Upload to which Mapillary user account", required=False
        )
        group.add_argument(
            "--organization_key",
            help="Specify organization ID",
            default=None,
            required=False,
        )
        group.add_argument(
            "--desc_path",
            help="Specify the path to read image description. Applicable for uploading image directories only",
            default=None,
            required=False,
        )
        group.add_argument(
            "--dry_run",
            help="Disable actual upload. Used for debugging only",
            action="store_true",
            default=False,
            required=False,
        )

    def run(self, vars_args: dict):
        upload_multiple(
            **(
                {
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(upload_multiple).args
                }
            )
        )
