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
