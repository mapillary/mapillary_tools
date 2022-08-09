import json
import logging
import os
import struct


LOG = logging.getLogger(__name__)
NODE_CHANNEL_FD = int(os.getenv("NODE_CHANNEL_FD", -1))


def _write(obj):
    # put here to make sure obj is JSON-serializable, and if not, fail early
    data = json.dumps(obj, separators=(",", ":")) + os.linesep

    if NODE_CHANNEL_FD == -1:
        # do nothing
        return

    if os.name == "nt":
        buf = data.encode("utf-8")
        # On windows, using node v8.11.4, this assertion fails
        # without sending the header
        # Assertion failed: ipc_frame.header.flags <= (UV_IPC_TCP_SERVER |
        # UV_IPC_RAW_DATA | UV_IPC_TCP_CONNECTION),
        # file src\win\pipe.c, line 1607
        header = struct.pack("<Q", 1) + struct.pack("<Q", len(buf))
        os.write(NODE_CHANNEL_FD, header + buf)
    else:
        os.write(NODE_CHANNEL_FD, data.encode("utf-8"))


def send(type, payload):
    obj = {
        "type": type,
        "payload": payload,
    }
    try:
        _write(obj)
    except Exception:
        LOG.warning(f"IPC error sending: {obj}", exc_info=True)
