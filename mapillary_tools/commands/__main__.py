import argparse
import logging
import sys

from .. import VERSION, exceptions
from . import (
    authenticate,
    process,
    process_and_upload,
    sample_video,
    upload,
    video_process,
    video_process_and_upload,
    zip,
)

mapillary_tools_commands = [
    process,
    upload,
    sample_video,
    video_process,
    authenticate,
    process_and_upload,
    video_process_and_upload,
    zip,
]


# do not use __name__ here is because if you run tools as a module, __name__ will be "__main__"
LOG = logging.getLogger("mapillary_tools")


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
            nargs="+",
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


def configure_logger(logger: logging.Logger, stream=None) -> None:
    formatter = logging.Formatter("%(asctime)s - %(levelname)-7s - %(message)s")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def main():
    parser = argparse.ArgumentParser(
        "mapillary_tool",
    )
    parser.add_argument(
        "--version",
        help="show the version of mapillary tools and exit",
        action="version",
        version=f"mapillary_tools version {VERSION}",
    )
    parser.add_argument(
        "--verbose",
        help="show verbose",
        action="store_true",
        default=False,
        required=False,
    )
    parser.set_defaults(func=lambda _: parser.print_help())

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

    log_level = logging.DEBUG if args.verbose else logging.INFO
    configure_logger(LOG, sys.stderr)
    LOG.setLevel(log_level)

    argvars = vars(args)
    params = {k: v for k, v in argvars.items() if v is not None and not callable(v)}
    for k, v in params.items():
        LOG.debug(f"CLI param: {k}: {v}")

    try:
        args.func(argvars)
    except exceptions.MapillaryUserError as exc:
        LOG.error(f"{exc.__class__.__name__}: {exc}")
        sys.exit(exc.exit_code)


if __name__ == "__main__":
    main()
