from . import ipc


def print_error(message):
    print(message)
    ipc.send_error(message)
