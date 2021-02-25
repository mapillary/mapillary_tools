import json
import os
import struct

NODE_CHANNEL_FD = int(os.getenv("NODE_CHANNEL_FD", -1))

if NODE_CHANNEL_FD == -1:

    def __write(obj):
        pass


elif os.name == "nt":

    def __write(obj):
        data = json.dumps(obj, separators=(",", ":")) + os.linesep
        buf = data.encode("utf-8")
        # On windows, using node v8.11.4, this assertion fails
        # without sending the header
        # Assertion failed: ipc_frame.header.flags <= (UV_IPC_TCP_SERVER |
        # UV_IPC_RAW_DATA | UV_IPC_TCP_CONNECTION),
        # file src\win\pipe.c, line 1607
        header = struct.pack("<Q", 1) + struct.pack("<Q", len(buf))
        os.write(NODE_CHANNEL_FD, header + buf)


else:

    def __write(obj):
        data = json.dumps(obj, separators=(",", ":")) + os.linesep
        os.write(NODE_CHANNEL_FD, data.encode("utf-8"))


def is_enabled():
    return NODE_CHANNEL_FD != -1


def send(type, payload):
    obj = {
        "type": type,
        "payload": payload,
    }
    try:
        __write(obj)
    except Exception as e:
        print(f"IPC error for: {obj}")
        print(f"Error: {e}")


def send_error(message):
    send("error", {"message": message})
