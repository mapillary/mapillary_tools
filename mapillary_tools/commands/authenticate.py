from ..edit_config import edit_config


class Command:
    name = "authenticate"
    help = "Helper tool : (Re)run authentication."

    def add_basic_arguments(self, parser):
        parser.add_argument(
            "--config_file",
            help="Full path to the config file to be edited. Default is ~/.config/mapillary/configs/MkJKbDA0bnZuZlcxeTJHTmFqN3g1dzo1YTM0NjRkM2EyZGU5MzBh",
            default=None,
            required=False,
        )
        parser.add_argument(
            "--user_name", help="Mapillary user name", default=None, required=False
        )
        parser.add_argument(
            "--user_email",
            help="user email, used to create Mapillary account",
            default=None,
            required=False,
        )
        parser.add_argument(
            "--user_password",
            help="password associated with the Mapillary user account",
            default=None,
            required=False,
        )
        parser.add_argument(
            "--jwt", help="JWT authentication token", default=None, required=False
        )
        parser.add_argument(
            "--user_key",
            help="Manually specify user key",
            default=False,
            required=False,
        )
        parser.add_argument(
            "--force_overwrite",
            help="Automatically overwrite any existing credentials stored in the config file for the specified user.",
            action="store_true",
            default=False,
            required=False,
        )

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):
        edit_config(**vars(args))
