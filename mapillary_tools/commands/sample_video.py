import os
import inspect
import argparse

from ..sample_video import sample_video


class Command:
    name = "sample_video"
    help = "sample video into images"

    def add_basic_arguments(self, parser: argparse.ArgumentParser):
        group = parser.add_argument_group("video process options")
        group.add_argument(
            "--video_sample_interval",
            help="Time interval for sampled video frames in seconds",
            default=2,
            type=float,
            required=False,
        )
        group.add_argument(
            "--video_duration_ratio",
            help="Real time video duration ratio of the under or oversampled video duration.",
            type=float,
            default=1.0,
            required=False,
        )
        group.add_argument(
            "--video_start_time",
            help="Video start time specified in YYYY_MM_DD_HH_MM_SS_sss in UTC. For example 2020_12_28_12_36_36_508 represents 2020-12-28T12:36:36.508Z",
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
            help="Re-sample all videos. Note it will REMOVE all the existing video sample directories",
            action="store_true",
            default=False,
            required=False,
        )
        group.add_argument(
            "--skip_sample_errors",
            help="Skip errors from the video sampling",
            action="store_true",
            default=False,
            required=False,
        )

    def run(self, vars_args: dict):
        video_import_path = vars_args["video_import_path"]
        import_path = vars_args["import_path"]
        if import_path is None:
            if os.path.isdir(video_import_path):
                import_path = os.path.join(
                    video_import_path, "mapillary_sampled_video_frames"
                )
            else:
                import_path = os.path.join(
                    os.path.dirname(video_import_path), "mapillary_sampled_video_frames"
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
