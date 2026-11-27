# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import logging
import sys
from pathlib import Path

import pytest
from mapillary_tools import exceptions
from mapillary_tools.commands import __main__ as commands
from mapillary_tools.commands.process import Command as ProcessCommand


def _run_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception):
    def _run(self, vars_args):
        raise error

    monkeypatch.setattr(ProcessCommand, "run", _run)
    monkeypatch.setattr(sys, "argv", ["mapillary_tools", "process", str(tmp_path)])
    with pytest.raises(SystemExit) as exit_info:
        commands.main()
    return exit_info.value.code


def test_unexpected_error_exits_1_with_its_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog
):
    with caplog.at_level(logging.ERROR):
        code = _run_process(monkeypatch, tmp_path, RuntimeError("boom"))

    assert code == 1
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert record.getMessage() == "Unexpected error: RuntimeError: boom"
    # Without --verbose too
    assert record.exc_info is not None
    assert "Traceback (most recent call last):" in caplog.text


def test_user_errors_keep_their_exit_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog
):
    error = exceptions.MapillaryFileNotFoundError("not found")
    assert _run_process(monkeypatch, tmp_path, error) == 3
    assert "Unexpected error" not in caplog.text
