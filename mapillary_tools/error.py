class MapillaryUserError(Exception):
    pass


class MapillaryGeoTaggingError(MapillaryUserError):
    pass


class MapillaryInterpolationError(MapillaryUserError):
    pass


class MapillaryGPXEmptyError(MapillaryInterpolationError):
    pass


class MapillaryOutsideGPXTrackError(MapillaryInterpolationError):
    def __init__(
        self, message, image_time: str, gpx_start_time: str, gpx_end_time: str
    ):
        super().__init__(message)
        self.image_time = image_time
        self.gpx_start_time = gpx_start_time
        self.gpx_end_time = gpx_end_time


class MapillaryStationaryBlackVueError(MapillaryUserError):
    pass


class MapillaryDuplicationError(MapillaryUserError):
    def __init__(self, message, desc):
        super().__init__(message)
        self.desc = desc
