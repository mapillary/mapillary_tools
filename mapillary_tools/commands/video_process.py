from .process import Command as ProcessCommand
from .sample_video import Command as SampleCommand


class Command:
    name = "video_process"
    help = "sample video into images and process the images"

    def add_basic_arguments(self, parser):
        SampleCommand().add_basic_arguments(parser)
        ProcessCommand().add_basic_arguments(parser)

    def run(self, args: dict):
        SampleCommand().run(args)
        ProcessCommand().run(args)
