import argparse
import inspect
from pathlib import Path

from .. import constants
from ..sample_video import sample_video


class Command:
    name = "sample_video"
    help = "sample video into images"

    def add_basic_arguments(self, parser: argparse.ArgumentParser):
        group = parser.add_argument_group(
            f"{constants.ANSI_BOLD}VIDEO PROCESS OPTIONS{constants.ANSI_RESET_ALL}"
        )
        group.add_argument(
            "--video_sample_distance",
            help="The minimal distance interval, in meters, for sampling video frames. [default: %(default)s]",
            default=constants.VIDEO_SAMPLE_DISTANCE,
            type=float,
            required=False,
        )
        group.add_argument(
            "--video_sample_interval",
            help="[DEPRECATED since v0.10.0] Time interval, in seconds, for sampling video frames. Since v0.10.0 you must disable distance-sampling with --video_sample_distance=-1 in order to apply this option. [default: %(default)s]",
            default=constants.VIDEO_SAMPLE_INTERVAL,
            type=float,
            required=False,
        )
        group.add_argument(
            "--video_duration_ratio",
            help="[DEPRECATED since v0.10.0] Real time video duration ratio of the under or oversampled video duration. [default: %(default)s]",
            type=float,
            default=constants.VIDEO_DURATION_RATIO,
            required=False,
        )
        group.add_argument(
            "--video_start_time",
            help="Video start time specified in YYYY_MM_DD_HH_MM_SS_sss in UTC. For example 2020_12_28_12_36_36_508 represents 2020-12-28T12:36:36.508Z.",
            default=None,
            required=False,
        )
        group.add_argument(
            "--skip_subfolders",
            help="Skip all subfolders and import only the images in the given directory path.",
            action="store_true",
            default=False,
            required=False,
        )
        group.add_argument(
            "--rerun",
            help="Re-sample all videos. Note it will REMOVE all the existing video sample directories.",
            action="store_true",
            default=False,
            required=False,
        )
        group.add_argument(
            "--skip_sample_errors",
            help="Skip errors from the video sampling.",
            action="store_true",
            default=False,
            required=False,
        )

    def run(self, vars_args: dict):
        video_import_path: Path = vars_args["video_import_path"]
        import_path = vars_args["import_path"]
        if import_path is None:
            if video_import_path.is_dir():
                import_path = video_import_path.joinpath(
                    constants.SAMPLED_VIDEO_FRAMES_FILENAME
                )
            else:
                import_path = video_import_path.resolve().parent.joinpath(
                    constants.SAMPLED_VIDEO_FRAMES_FILENAME
                )
            vars_args["import_path"] = import_path

        sample_video(
            **(
                {
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(sample_video).args
                }
            )
        )
