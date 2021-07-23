from .process import Command as ProcessCommand
from .sample_video import Command as SampleCommand
from .upload import Command as UploadCommand


class Command:
    name = "video_process_and_upload"
    help = "sample video into images, process the images and upload to Mapillary"

    def add_basic_arguments(self, parser):
        SampleCommand().add_basic_arguments(parser)
        ProcessCommand().add_basic_arguments(parser)
        UploadCommand().add_basic_arguments(parser)

    def run(self, args: dict):
        SampleCommand().run(args)
        ProcessCommand().run(args)
        UploadCommand().run(args)
