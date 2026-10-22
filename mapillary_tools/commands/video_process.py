# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import logging
from pathlib import Path

from .. import constants, exceptions
from ..sample_video import find_sample_dirs
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

        if args["skip_subfolders"]:
            _add_sample_dirs(args)

        ProcessCommand().run(args)

        if sample_error is not None:
            raise sample_error


def _add_sample_dirs(args: dict) -> None:
    """
    Add the folders that the videos were sampled into to the import paths.
    --skip_subfolders chose the videos to sample, and hides the subfolders of
    the import path from processing (and from uploading in
    video_process_and_upload), which the samples of each video are in
    """
    import_path: Path = args["import_path"]
    sample_dirs = [
        sample_dir
        for sample_dir in find_sample_dirs(
            args["video_import_path"], import_path, skip_subfolders=True
        )
        # Not a video that failed to sample
        if sample_dir.is_dir()
    ]
    if not sample_dirs:
        return

    if args.get("desc_path") is None:
        # Where process writes it for the import path alone, rather than to
        # STDOUT, as for several import paths
        args["desc_path"] = str(
            import_path.joinpath(constants.IMAGE_DESCRIPTION_FILENAME)
        )

    args["import_path"] = [import_path, *sample_dirs]
