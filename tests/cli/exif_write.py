# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import logging
import sys
from pathlib import Path

from mapillary_tools.exif_write import ExifEdit

LOG = logging.getLogger(__name__)


if __name__ == "__main__":
    LOG.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.DEBUG)
    LOG.addHandler(handler)
    for image in sys.argv[1:]:
        edit = ExifEdit(Path(image))
        edit.dump_image_bytes()
