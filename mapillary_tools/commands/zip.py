import argparse
import inspect
from pathlib import Path

from ..upload import zip_images


class Command:
    name = "zip"
    help = "zip images into sequences"

    def add_basic_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "import_path",
            help="Path to your images.",
            type=Path,
        )
        parser.add_argument(
            "zip_dir",
            help="Path to store zipped images.",
            type=Path,
        )
        parser.add_argument(
            "--desc_path",
            help='Specify the path to read image description. If it is "-", then read from STDIN.',
            default=None,
            required=False,
        )

    def run(self, vars_args: dict):
        zip_images(
            **(
                {
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(zip_images).args
                }
            )
        )
