from .upload import Command as UploadCommand
from .video_process import Command as VideoProcessCommand


class Command:
    name = "video_process_and_upload"
    help = "sample video into images, process the images and upload to Mapillary"

    def add_basic_arguments(self, parser):
        VideoProcessCommand().add_basic_arguments(parser)
        UploadCommand().add_basic_arguments(parser)

    def run(self, args: dict):
        if args.get("desc_path") is None:
            # \x00 is a special path similiar to /dev/null
            # it tells process command do not write anything
            args["desc_path"] = "\x00"
        VideoProcessCommand().run(args)
        UploadCommand().run(args)
