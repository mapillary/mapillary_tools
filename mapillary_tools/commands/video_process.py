from .process import Command as ProcessCommand
from .sample_video import Command as SampleCommand
from ..apply_camera_specific_config import apply_camera_specific_config


class Command:
    name = "video_process"
    help = "sample video into images and process the images"

    def add_basic_arguments(self, parser):
        SampleCommand().add_basic_arguments(parser)
        ProcessCommand().add_basic_arguments(parser)

    def run(self, args: dict):
        vars_args = apply_camera_specific_config(args)
        SampleCommand().run(vars_args)
        ProcessCommand().run(vars_args)
