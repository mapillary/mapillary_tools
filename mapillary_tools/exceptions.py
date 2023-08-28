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


class MapillaryExiftoolNotFoundError(MapillaryUserError):
    exit_code = 8


class MapillaryDescriptionError(Exception):
    pass


class MapillaryGeoTaggingError(MapillaryDescriptionError):
    pass


class MapillaryGPXEmptyError(MapillaryDescriptionError, MapillaryUserError):
    exit_code = 9


class MapillaryVideoGPSNotFoundError(MapillaryDescriptionError, MapillaryUserError):
    exit_code = 9


class MapillaryGPSNoiseError(MapillaryDescriptionError):
    pass


class MapillaryOutsideGPXTrackError(MapillaryDescriptionError):
    def __init__(
        self, message: str, image_time: str, gpx_start_time: str, gpx_end_time: str
    ):
        super().__init__(message)
        self.image_time = image_time
        self.gpx_start_time = gpx_start_time
        self.gpx_end_time = gpx_end_time


class MapillaryStationaryVideoError(MapillaryDescriptionError, MapillaryUserError):
    exit_code = 10


class MapillaryInvalidBlackVueVideoError(MapillaryDescriptionError, MapillaryUserError):
    exit_code = 11


class MapillaryDuplicationError(MapillaryDescriptionError):
    def __init__(
        self,
        message: str,
        desc: T.Mapping[str, T.Any],
        distance: float,
        angle_diff: T.Optional[float],
    ) -> None:
        super().__init__(message)
        self.desc = desc
        self.distance = distance
        self.angle_diff = angle_diff


class MapillaryUploadedAlreadyError(MapillaryDescriptionError):
    def __init__(
        self,
        message: str,
        desc: T.Mapping[str, T.Any],
    ) -> None:
        super().__init__(message)
        self.desc = desc


class MapillaryEXIFNotFoundError(MapillaryDescriptionError):
    pass


class MapillaryUploadConnectionError(MapillaryUserError):
    exit_code = 12


class MapillaryUploadTimeoutError(MapillaryUserError):
    exit_code = 13


class MapillaryUploadUnauthorizedError(MapillaryUserError):
    exit_code = 14


class MapillaryMetadataValidationError(MapillaryUserError, MapillaryDescriptionError):
    exit_code = 15
