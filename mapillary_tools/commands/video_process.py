# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import logging

from .. import exceptions
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
        sample_error: exceptions.MapillaryVideoSampleError | None = None
        try:
            SampleCommand().run(args)
        except exceptions.MapillaryVideoSampleError as ex:
            # Like the process command, which writes out the files it did
            # process before failing: process the frames of the videos that
            # did sample rather than leave them behind, then fail
            sample_error = ex

        option = "filetypes"
        if args[option] != {FileType.IMAGE}:
            LOG.warning(
                'Force the option "%s" to be "%s" to avoid processing and uploading both the video samples and the videos themselves',
                option,
                FileType.IMAGE.value,
            )
            args[option] = {FileType.IMAGE}

        ProcessCommand().run(args)

        if sample_error is not None:
            raise sample_error
