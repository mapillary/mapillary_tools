# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import inspect
import logging

from .. import exceptions
from ..authenticate import fetch_user_items
from .upload import Command as UploadCommand
from .video_process import Command as VideoProcessCommand


LOG = logging.getLogger(__name__)


class Command:
    name = "video_process_and_upload"
    help = "sample video into images, process the images and upload to Mapillary"

    def add_basic_arguments(self, parser):
        VideoProcessCommand().add_basic_arguments(parser)
        UploadCommand().add_basic_arguments(parser)

    def run(self, vars_args: dict):
        if vars_args.get("desc_path") is None:
            # \x00 is a special path similiar to /dev/null
            # it tells process command do not write anything
            vars_args["desc_path"] = "\x00"

        if "user_items" not in vars_args:
            vars_args["user_items"] = fetch_user_items(
                **{
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(fetch_user_items).args
                }
            )

        try:
            VideoProcessCommand().run(vars_args)
        except exceptions.MapillaryVideoSampleError:
            # Upload only some of the videos when asked to, as process_and_upload
            # does with the files it fails to process. But say so: the last thing
            # logged before this is the process summary of the sample images that
            # were ready to upload
            LOG.error(
                "Nothing was uploaded, because some videos failed to sample. "
                "To upload the sample images of the others, specify --skip_sample_errors"
            )
            raise

        UploadCommand().run(vars_args)
