from __future__ import annotations

import typing as T


class MapillaryUserError(Exception):
    exit_code: int


class MapillaryProcessError(MapillaryUserError):
    """
    Base exception for process specific errors
    """

    exit_code = 6


class MapillaryDescriptionError(Exception):
    pass


class MapillaryBadParameterError(MapillaryUserError):
    exit_code = 2


class MapillaryFileNotFoundError(MapillaryUserError):
    exit_code = 3


class MapillaryInvalidDescriptionFile(MapillaryUserError):
    exit_code = 4


class MapillaryVideoError(MapillaryUserError):
    exit_code = 7


class MapillaryFFmpegNotFoundError(MapillaryUserError):
    exit_code = 8


class MapillaryExiftoolNotFoundError(MapillaryUserError):
    exit_code = 8


class MapillaryGeoTaggingError(MapillaryDescriptionError):
    pass


class MapillaryVideoGPSNotFoundError(MapillaryDescriptionError):
    pass


class MapillaryGPXEmptyError(MapillaryDescriptionError):
    pass


class MapillaryGPSNoiseError(MapillaryDescriptionError):
    pass


class MapillaryStationaryVideoError(MapillaryDescriptionError):
    pass


class MapillaryOutsideGPXTrackError(MapillaryDescriptionError):
    def __init__(
        self, message: str, image_time: str, gpx_start_time: str, gpx_end_time: str
    ):
        super().__init__(message)
        self.image_time = image_time
        self.gpx_start_time = gpx_start_time
        self.gpx_end_time = gpx_end_time


class MapillaryDuplicationError(MapillaryDescriptionError):
    def __init__(
        self,
        message: str,
        desc: T.Mapping[str, T.Any],
        distance: float,
        angle_diff: float | None,
    ) -> None:
        super().__init__(message)
        self.desc = desc
        self.distance = distance
        self.angle_diff = angle_diff


class MapillaryExifToolXMLNotFoundError(MapillaryDescriptionError):
    pass


class MapillaryFileTooLargeError(MapillaryDescriptionError):
    pass


class MapillaryCaptureSpeedTooFastError(MapillaryDescriptionError):
    pass


class MapillaryNullIslandError(MapillaryDescriptionError):
    pass


class MapillaryUploadConnectionError(MapillaryUserError):
    exit_code = 12


class MapillaryUploadTimeoutError(MapillaryUserError):
    exit_code = 13


class MapillaryUploadUnauthorizedError(MapillaryUserError):
    exit_code = 14


class MapillaryMetadataValidationError(MapillaryUserError):
    exit_code = 15
