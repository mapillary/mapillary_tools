
from mapillary_tools.process_video import (
    add_video_arguments,
    sample_video)


class Command:
    name = 'sample_video'
    help = "Main tool : Sample video into images."

    def add_basic_arguments(self, parser):
        add_video_arguments(parser)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):

        # sample video
        sample_video(**vars(args))
