# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import json
import struct
from unittest.mock import patch

import pytest

from mapillary_tools import ipc


class TestIPCWrite:
    def test_write_rejects_non_serializable(self):
        """json.dumps runs before the FD check, so non-serializable raises."""
        with patch.object(ipc, "NODE_CHANNEL_FD", -1):
            with pytest.raises(TypeError):
                ipc._write({"func": lambda: None})

    @patch("os.write")
    def test_write_unix(self, mock_write):
        """Unix path writes JSON + linesep directly to the fd."""
        with patch.object(ipc, "NODE_CHANNEL_FD", 42), patch("os.name", "posix"):
            ipc._write({"key": "value"})
            mock_write.assert_called_once()
            fd, raw = mock_write.call_args[0]
            assert fd == 42
            parsed = json.loads(raw.decode("utf-8").strip())
            assert parsed == {"key": "value"}

    @patch("os.write")
    def test_write_windows(self, mock_write):
        """Windows path prepends a 16-byte header: uint64(1) + uint64(payload_len)."""
        with patch.object(ipc, "NODE_CHANNEL_FD", 42), patch("os.name", "nt"):
            ipc._write({"key": "value"})
            mock_write.assert_called_once()
            fd, raw = mock_write.call_args[0]
            assert fd == 42
            # Verify the 16-byte header
            header = raw[:16]
            flag, payload_len = struct.unpack("<QQ", header)
            assert flag == 1
            # Verify the payload after the header is valid JSON
            payload = raw[16:]
            assert len(payload) == payload_len
            parsed = json.loads(payload.decode("utf-8").strip())
            assert parsed == {"key": "value"}
