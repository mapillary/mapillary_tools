import logging

from ..process_geotag_properties import GeotagSource
from ..types import FileType
from .process import Command as ProcessCommand
from .sample_video import Command as SampleCommand


LOG = logging.getLogger(__name__)


class Command:
    name = "video_process"
    help = "sample video into images and process the images"

    def add_basic_arguments(self, parser):
        SampleCommand().add_basic_arguments(parser)
        ProcessCommand().add_basic_arguments(parser)

    def run(self, args: dict):
        SampleCommand().run(args)

        option = "filetypes"
        if args[option] != {FileType.IMAGE}:
            LOG.warning(
                'Force the option "%s" to be "%s" to avoid processing and uploading both the video samples and the videos themselves',
                option,
                FileType.IMAGE.value,
            )
            args[option] = {FileType.IMAGE}

        if 0 <= args["video_sample_distance"]:
            expected: GeotagSource = "exif"
            option = "geotag_source"
            if args[option] != expected:
                LOG.warning(
                    (
                        "Since sample geotags have been written in EXIFs when you sampled videos by distance (%s meter(s)),"
                        ' so we force the option "%s" to be "%s"'
                        " to avoid unnecessary geotagging from the videos again"
                    ),
                    args["video_sample_distance"],
                    option,
                    expected,
                )
                args[option] = expected

        ProcessCommand().run(args)
