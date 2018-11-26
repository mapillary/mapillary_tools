#!/usr/bin/env python

import os
import json
import struct
import time

NODE_CHANNEL_FD = int(os.getenv('NODE_CHANNEL_FD', -1))

if NODE_CHANNEL_FD == -1:
    def __write(obj):
        pass

elif os.name == 'nt':
    def __write(obj):
        data = json.dumps(obj, separators=(',', ':')
                          ).encode('utf-8') + os.linesep
        # On windows, using node v8.11.4, this assertion fails
        # without sending the header
        # Assertion failed: ipc_frame.header.flags <= (UV_IPC_TCP_SERVER |
        # UV_IPC_RAW_DATA | UV_IPC_TCP_CONNECTION),
        # file src\win\pipe.c, line 1607
        header = struct.pack('<Q', 1) + struct.pack('<Q', len(data))
        os.write(NODE_CHANNEL_FD, header + data)

else:
    def __write(obj):
        data = json.dumps(obj, separators=(',', ':')
                          ).encode('utf-8') + os.linesep
        os.write(NODE_CHANNEL_FD, data)

def is_enabled():
    return NODE_CHANNEL_FD != -1

def send(type, payload):
    __write({
        'type': type,
        'payload': payload,
    })

def send_error(message):
    send('error', {'message': message})


