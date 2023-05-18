import typing as T


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
    exit_code = 8
    help = "https://github.com/mapillary/mapillary_tools#video-support"


class _MapillaryDescriptionError(Exception):
    pass


class MapillaryGeoTaggingError(_MapillaryDescriptionError):
    pass


class MapillaryGPXEmptyError(_MapillaryDescriptionError, MapillaryUserError):
    exit_code = 9


class MapillaryOutsideGPXTrackError(_MapillaryDescriptionError):
    def __init__(
        self, message: str, image_time: str, gpx_start_time: str, gpx_end_time: str
    ):
        super().__init__(message)
        self.image_time = image_time
        self.gpx_start_time = gpx_start_time
        self.gpx_end_time = gpx_end_time


class MapillaryStationaryVideoError(_MapillaryDescriptionError, MapillaryUserError):
    exit_code = 10


class MapillaryInvalidBlackVueVideoError(
    _MapillaryDescriptionError, MapillaryUserError
):
    exit_code = 11


class MapillaryDuplicationError(_MapillaryDescriptionError):
    def __init__(
        self,
        message: str,
        desc: T.Mapping,
        distance: float,
        angle_diff: T.Optional[float],
    ) -> None:
        super().__init__(message)
        self.desc = desc
        self.distance = distance
        self.angle_diff = angle_diff


class MapillaryUploadedAlreadyError(_MapillaryDescriptionError):
    def __init__(
        self,
        message: str,
        desc: T.Mapping,
    ) -> None:
        super().__init__(message)
        self.desc = desc


class MapillaryUploadConnectionError(MapillaryUserError):
    exit_code = 12


class MapillaryUploadTimeoutError(MapillaryUserError):
    exit_code = 13


class MapillaryUploadUnauthorizedError(MapillaryUserError):
    exit_code = 14
