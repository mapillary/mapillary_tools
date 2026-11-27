# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import argparse

import pytest
from mapillary_tools.commands import (
    process,
    process_and_upload,
    video_process,
    video_process_and_upload,
)


def _option_strings(command) -> set:
    # As the command line builds it
    parser = argparse.ArgumentParser(conflict_handler="resolve")
    command.Command().add_basic_arguments(parser)
    return {option for action in parser._actions for option in action.option_strings}


@pytest.mark.parametrize("command", [process, process_and_upload])
def test_process_takes_the_file_time_option(command):
    assert "--use_file_time_as_capture_time" in _option_strings(command)


@pytest.mark.parametrize("command", [video_process, video_process_and_upload])
def test_video_process_does_not(command):
    """The frames get their times from the video"""
    options = _option_strings(command)
    assert "--use_file_time_as_capture_time" not in options
    # The other process options are still there
    assert "--geotag_source" in options
