# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import argparse
import inspect
import json
import sys

from ..upload import check_upload_history
from .process import bold_text


class Command:
    name = "check_upload_history"
    help = "Check whether processed data exists in local upload history"

    def add_basic_arguments(self, parser: argparse.ArgumentParser):
        group = parser.add_argument_group(bold_text("UPLOAD HISTORY OPTIONS"))
        group.add_argument(
            "--desc_path",
            help=(
                "Path to the description file with processed image and video metadata."
            ),
            default=None,
            required=False,
        )

    def run(self, vars_args: dict):
        results = check_upload_history(
            **{
                key: value
                for key, value in vars_args.items()
                if key in inspect.getfullargspec(check_upload_history).args
            }
        )
        json.dump(results, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
