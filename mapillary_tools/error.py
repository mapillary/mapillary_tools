from . import ipc


def print_error(message):
    print(message)
    ipc.send_error(message)


class MapillaryUserError(Exception):
    pass


class MapillaryGeoTaggingError(MapillaryUserError):
    pass
