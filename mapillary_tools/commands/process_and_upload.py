from .process import Command as ProcessCommand
from .upload import Command as UploadCommand


class Command:
    name = "process_and_upload"
    help = "process images or videos and upload to Mapillary"

    def add_basic_arguments(self, parser):
        ProcessCommand().add_basic_arguments(parser)
        UploadCommand().add_basic_arguments(parser)

    def run(self, args: dict):
        if args.get("desc_path") is None:
            # \x00 is a special path similiar to /dev/null
            # it tells process command do not write anything
            args["desc_path"] = "\x00"
        ProcessCommand().run(args)
        UploadCommand().run(args)
