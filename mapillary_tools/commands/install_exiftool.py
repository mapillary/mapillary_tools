# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import argparse
import logging

from .. import constants, exiftool_install


LOG = logging.getLogger(__name__)


class Command:
    name = "install_exiftool"
    help = "install the latest ExifTool for mapillary_tools to read GPS with"

    def add_basic_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "--force",
            help="Install the latest ExifTool even if this version of mapillary_tools installed one already.",
            action="store_true",
            default=False,
            required=False,
        )

    def run(self, vars_args: dict):
        executable = exiftool_install.install_exiftool(force=vars_args["force"])
        if constants.EXIFTOOL_PATH is not None:
            LOG.warning(
                "MAPILLARY_TOOLS_EXIFTOOL_PATH is set, so mapillary_tools runs %s instead",
                constants.EXIFTOOL_PATH,
            )
        print(executable)
