from .process import Command as ProcessCommand
from .upload import Command as UploadCommand


class Command:
    name = "process_and_upload"
    help = "process images and upload to Mapillary"

    def add_basic_arguments(self, parser):
        ProcessCommand().add_basic_arguments(parser)
        UploadCommand().add_basic_arguments(parser)

    def run(self, args: dict):
        ProcessCommand().run(args)
        UploadCommand().run(args)
