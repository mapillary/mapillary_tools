# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import os
import tempfile

# Tests never download ExifTool, nor run the one that mapillary_tools installed
# for the user: they run the exiftool on the PATH, or MAPILLARY_TOOLS_EXIFTOOL_PATH.
# Set before mapillary_tools is imported, for the tests and for the
# mapillary_tools commands that they run
os.environ.setdefault("MAPILLARY_TOOLS_EXIFTOOL_AUTO_INSTALL", "NO")
os.environ.setdefault(
    "MAPILLARY_TOOLS_EXIFTOOL_INSTALL_DIR",
    os.path.join(tempfile.gettempdir(), f"mapillary_tools_tests_{os.getpid()}"),
)
