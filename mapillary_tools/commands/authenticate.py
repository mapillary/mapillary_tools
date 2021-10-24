import argparse
import inspect

from ..edit_config import edit_config


class Command:
    name = "authenticate"
    help = "authenticate Mapillary users"

    def add_basic_arguments(self, parser: argparse.ArgumentParser):
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

    def run(self, vars_args: dict):
        edit_config(
            **(
                {
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(edit_config).args
                }
            )
        )
