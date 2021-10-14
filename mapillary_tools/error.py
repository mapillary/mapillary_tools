class MapillaryUserError(Exception):
    pass


class MapillaryGeoTaggingError(MapillaryUserError):
    pass


class MapillaryInterpolationError(MapillaryUserError):
    pass


class MapillaryStationaryBlackVueError(MapillaryUserError):
    pass


class MapillaryDuplicationError(MapillaryUserError):
    def __init__(self, message, desc):
        super().__init__(message)
        self.desc = desc
