import argparse
import inspect

from ..authenticate import authenticate


class Command:
    name = "authenticate"
    help = "authenticate Mapillary users"

    def add_basic_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "--user_name", help="Mapillary user name", default=None, required=False
        )
        parser.add_argument(
            "--user_email",
            help="User email, used to create Mapillary account",
            default=None,
            required=False,
        )
        parser.add_argument(
            "--user_password",
            help="Password associated with the Mapillary user account",
            default=None,
            required=False,
        )
        parser.add_argument(
            "--jwt", help="Mapillary user access token", default=None, required=False
        )

    def run(self, vars_args: dict):
        authenticate(
            **(
                {
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(authenticate).args
                }
            )
        )
