import argparse
import enum
import logging
import sys
from pathlib import Path

import requests

from .. import api_v4, constants, exceptions, VERSION
from ..upload import log_exception
from ..utils import configure_logger, get_app_name
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


# Root logger of mapillary_tools (not including third-party libraries)
LOG = logging.getLogger(get_app_name())


# Handle shared arguments/options here
def add_general_arguments(parser, command):
    if command in ["sample_video", "video_process", "video_process_and_upload"]:
        parser.add_argument(
            "video_import_path",
            help="Path to a video or directory with one or more video files.",
            type=Path,
        )
        parser.add_argument(
            "import_path",
            help=f"Path to where the images from video sampling will be saved. [default: {{VIDEO_IMPORT_PATH}}/{constants.SAMPLED_VIDEO_FRAMES_FILENAME}]",
            nargs="?",
            type=Path,
        )
        parser.add_argument(
            "--skip_subfolders",
            help="Skip all subfolders and import only the images in the given VIDEO_IMPORT_PATH.",
            action="store_true",
            default=False,
            required=False,
        )
    elif command in ["upload"]:
        parser.add_argument(
            "import_path",
            help="Paths to your images or videos.",
            nargs="+",
            type=Path,
        )
    elif command in ["process", "process_and_upload"]:
        parser.add_argument(
            "import_path",
            help="Paths to your images or videos.",
            nargs="+",
            type=Path,
        )
        parser.add_argument(
            "--skip_subfolders",
            help="Skip all subfolders and import only the images in the given IMPORT_PATH.",
            action="store_true",
            default=False,
            required=False,
        )


def _log_params(argvars: dict) -> None:
    MAX_ENTRIES = 5

    def _stringify(x) -> str:
        if isinstance(x, enum.Enum):
            return x.value
        else:
            return str(x)

    for k, v in argvars.items():
        if v is None:
            continue
        if callable(v):
            continue
        if k in ["jwt", "user_password"]:
            assert isinstance(v, str), type(v)
            v = "******"
        if isinstance(v, (list, set, tuple)):
            entries = [_stringify(x) for x in v]
            if len(entries) <= MAX_ENTRIES:
                v = ", ".join(entries)
            else:
                v = (
                    ", ".join(entries[:MAX_ENTRIES])
                ) + f" and {len(entries) - MAX_ENTRIES} more"
        else:
            v = _stringify(v)
        LOG.debug("CLI param: %s: %s", k, v)


def main():
    version_text = f"mapillary_tools version {VERSION}"

    parser = argparse.ArgumentParser(
        "mapillary_tool",
    )
    parser.add_argument(
        "--version",
        help="show the version of mapillary tools and exit",
        action="version",
        version=version_text,
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

    configure_logger(LOG, level=logging.DEBUG if args.verbose else logging.INFO)

    LOG.debug("%s", version_text)
    argvars = vars(args)
    _log_params(argvars)

    try:
        args.func(argvars)
    except requests.HTTPError as ex:
        log_exception(ex)
        # TODO: standardize exit codes as exceptions.MapillaryUserError
        sys.exit(16)

    except api_v4.HTTPContentError as ex:
        log_exception(ex)
        sys.exit(17)

    except exceptions.MapillaryUserError as ex:
        log_exception(ex)
        sys.exit(ex.exit_code)

    except KeyboardInterrupt:
        LOG.info("Interrupted by user...")
        sys.exit(130)


if __name__ == "__main__":
    main()
