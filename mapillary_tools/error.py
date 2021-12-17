class MapillaryUserError(Exception):
    exit_code: int


class MapillaryBadParameterError(MapillaryUserError):
    exit_code = 2


class MapillaryFileNotFoundError(MapillaryUserError):
    exit_code = 3


class MapillaryInvalidDescriptionFile(MapillaryUserError):
    exit_code = 4


class MapillaryUnknownFileTypeError(MapillaryUserError):
    exit_code = 5


class MapillaryProcessError(MapillaryUserError):
    exit_code = 6


class MapillaryVideoError(MapillaryUserError):
    exit_code = 7


class MapillaryFFmpegNotFoundError(MapillaryUserError):
    help = "https://github.com/mapillary/mapillary_tools#video-support"


class MapillaryFFprobeNotFoundError(MapillaryUserError):
    help = "https://github.com/mapillary/mapillary_tools#video-support"


class _MapillaryDescriptionError(Exception):
    pass


class MapillaryGeoTaggingError(_MapillaryDescriptionError):
    pass


class MapillaryGPXEmptyError(_MapillaryDescriptionError):
    pass


class MapillaryOutsideGPXTrackError(_MapillaryDescriptionError):
    def __init__(
        self, message, image_time: str, gpx_start_time: str, gpx_end_time: str
    ):
        super().__init__(message)
        self.image_time = image_time
        self.gpx_start_time = gpx_start_time
        self.gpx_end_time = gpx_end_time


class MapillaryStationaryBlackVueError(_MapillaryDescriptionError):
    pass


# FIXME: sequence error
class MapillaryDuplicationError(_MapillaryDescriptionError):
    def __init__(self, message, desc):
        super().__init__(message)
        self.desc = desc
