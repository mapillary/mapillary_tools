import argparse
import logging
import sys

from . import VERSION
from .commands import authenticate
from .commands import process
from .commands import process_and_upload
from .commands import sample_video
from .commands import upload
from .commands import video_process
from .commands import video_process_and_upload
from .commands import zip

mapillary_tools_commands = [
    process,
    zip,
    upload,
    process_and_upload,
    sample_video,
    video_process,
    video_process_and_upload,
    authenticate,
]


LOG = logging.getLogger()


def add_general_arguments(parser, command):
    if command == "authenticate":
        return

    if command in ["sample_video", "video_process", "video_process_and_upload"]:
        parser.add_argument(
            "video_import_path",
            help="Path to a video or directory with one or more video files.",
        )
        parser.add_argument(
            "import_path",
            help='Path to where the images from video sampling will be saved. If not specified, it will default to "mapillary_sampled_video_frames" under your video import path',
            nargs="?",
        )
        parser.add_argument(
            "--skip_subfolders",
            help="Skip all subfolders and import only the images in the given video_import_path",
            action="store_true",
            default=False,
            required=False,
        )
    elif command in ["upload"]:
        parser.add_argument(
            "import_path",
            help="Path to your images",
        )
    elif command in ["zip"]:
        parser.add_argument(
            "import_path",
            help="Path to your images",
        )
        parser.add_argument(
            "zip_dir",
            help="Path to store zipped images",
        )
    else:
        parser.add_argument(
            "import_path",
            help="Path to your images",
        )
        parser.add_argument(
            "--skip_subfolders",
            help="Skip all subfolders and import only the images in the given import_path",
            action="store_true",
            default=False,
            required=False,
        )


def main():
    parser = argparse.ArgumentParser(
        "mapillary_tool",
    )
    parser.add_argument(
        "--version",
        help="show the version of mapillary tools and exit",
        action="version",
        version=f"Mapillary tools version : {VERSION}",
    )

    all_commands = [module.Command() for module in mapillary_tools_commands]

    subparsers = parser.add_subparsers(
        description="please choose one of the available subcommands",
    )
    for command in all_commands:
        cmd_parser = subparsers.add_parser(
            command.name, help=command.help, conflict_handler="resolve"
        )
        add_general_arguments(cmd_parser, command.name)
        command.add_basic_arguments(cmd_parser)
        cmd_parser.set_defaults(func=command.run)

    args = parser.parse_args()
    args.func(vars(args))


if __name__ == "__main__":
    main()
