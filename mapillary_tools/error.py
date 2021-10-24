class MapillaryUserError(Exception):
    exit_code: int = 2


class MapillaryFileError(MapillaryUserError):
    exit_code = 3


class MapillaryBadParameterError(MapillaryUserError):
    exit_code = 2


class MapillaryProcessError(MapillaryUserError):
    exit_code = 20
    help = "https://github.com/mapillary/mapillary_tools#MapillaryProcessError"


class MapillaryGeoTaggingError(MapillaryUserError):
    pass


class _MapillaryInterpolationError(MapillaryGeoTaggingError):
    pass


class MapillaryGPXEmptyError(MapillaryGeoTaggingError):
    help = "https://github.com/mapillary/mapillary_tools#MapillaryGPXEmptyError"


class MapillaryVideoError(MapillaryUserError):
    pass


class MapillaryFFmpegNotFoundError(MapillaryUserError):
    help = "https://github.com/mapillary/mapillary_tools#video-support"


class MapillaryFFprobeNotFoundError(MapillaryUserError):
    help = "https://github.com/mapillary/mapillary_tools#video-support"


class MapillaryOutsideGPXTrackError(_MapillaryInterpolationError):
    help = "https://github.com/mapillary/mapillary_tools#MapillaryOutsideGPXTrackError"

    def __init__(
        self, message, image_time: str, gpx_start_time: str, gpx_end_time: str
    ):
        super().__init__(message)
        self.image_time = image_time
        self.gpx_start_time = gpx_start_time
        self.gpx_end_time = gpx_end_time


class MapillaryUploadAPIError(MapillaryUserError):
    pass


class MapillaryStationaryBlackVueError(MapillaryGeoTaggingError):
    pass


# FIXME: sequence error
class MapillaryDuplicationError(MapillaryUserError):
    help = "https://github.com/mapillary/mapillary_tools#MapillaryDuplicationError"

    def __init__(self, message, desc):
        super().__init__(message)
        self.desc = desc
