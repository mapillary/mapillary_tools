# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import argparse
import inspect

from ..authenticate import authenticate


class Command:
    name = "authenticate"
    help = "authenticate Mapillary users"

    def add_basic_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "--user_name", help="Mapillary user profile", default=None, required=False
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
        parser.add_argument(
            "--delete",
            help="Delete the specified user profile, or with --organization_name, only that saved organization name",
            default=False,
            required=False,
            action="store_true",
        )
        parser.add_argument(
            "--organization_key",
            help="The Mapillary organization ID to save in the user profile under --organization_name NAME. An existing profile is not logged in again, unless login options are given.",
            default=None,
            required=False,
        )
        parser.add_argument(
            "--organization_name",
            help="With --organization_key ID, save the ID under this name in the user profile, to upload with --organization_name NAME. With --delete, delete the saved name. Names are 2 to 32 letters, numbers, hyphens and underscores, starting with a letter.",
            default=None,
            required=False,
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
