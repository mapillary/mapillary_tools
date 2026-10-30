# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

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


class MapillaryVideoSampleError(MapillaryVideoError):
    """
    Raised after sampling every video if any of them failed
    """


class MapillaryFFmpegNotFoundError(MapillaryUserError):
    exit_code = 8


class MapillaryExiftoolNotFoundError(MapillaryUserError):
    exit_code = 8


class MapillaryGeoTaggingError(MapillaryDescriptionError):
    pass


class MapillaryUnsupportedFileError(MapillaryDescriptionError):
    """
    A file named for processing is neither an image nor a video that can be
    processed
    """


class MapillaryVideoGPSUnusableError(MapillaryDescriptionError):
    """
    The video has no GPS track that can be used: none at all, an empty one, or
    one too noisy to trust. Catch this rather than any one of its subclasses
    """


class MapillaryVideoGPSNotFoundError(MapillaryVideoGPSUnusableError):
    pass


class MapillaryInvalidGPXError(MapillaryDescriptionError):
    pass


class MapillaryInvalidVideoError(MapillaryDescriptionError):
    pass


class MapillaryGPXEmptyError(MapillaryVideoGPSUnusableError):
    pass


class MapillaryGPSNoiseError(MapillaryVideoGPSUnusableError):
    pass


class MapillaryStationaryVideoError(MapillaryDescriptionError):
    pass


class MapillaryProcessWarning(UserWarning):
    """
    Base class for what processing warns of about a file that it still
    processes: logged, never raised
    """


class MapillaryGPXAlignmentWarning(MapillaryProcessWarning):
    """
    A GPX track assumed to start with a video without a GPS clock lasts longer
    or shorter than the video: the video start time needs aligning with the
    track. A track that lasts longer (gpx_longer) may be that of a timelapse.
    Durations are in seconds, the GPX times capture times.
    """

    def __init__(
        self,
        message: str,
        video_duration: float,
        gpx_duration: float,
        gpx_start_time: str,
        gpx_end_time: str,
        gpx_longer: bool,
    ):
        super().__init__(message)
        self.video_duration = video_duration
        self.gpx_duration = gpx_duration
        self.gpx_start_time = gpx_start_time
        self.gpx_end_time = gpx_end_time
        self.gpx_longer = gpx_longer

    def __reduce__(self):
        # Pickle with every argument, so that the warning survives the trip
        # back from a worker process (video geotagging warns in one)
        return (
            self.__class__,
            (
                self.args[0],
                self.video_duration,
                self.gpx_duration,
                self.gpx_start_time,
                self.gpx_end_time,
                self.gpx_longer,
            ),
        )


class MapillaryGPXVideoStartUnknownError(MapillaryDescriptionError):
    """
    Nothing says how a GPX track lines up with a video without a GPS clock:
    the track is too long either to assume that it starts with the video, or,
    when it is said to, to end with it at the rate the video is said to run.
    """


# A geotagging error, so that the next geotag source gets its turn: a GPX track
# that misses the capture time says nothing about the file itself
class MapillaryOutsideGPXTrackError(MapillaryGeoTaggingError):
    def __init__(
        self, message: str, image_time: str, gpx_start_time: str, gpx_end_time: str
    ):
        super().__init__(message)
        self.image_time = image_time
        self.gpx_start_time = gpx_start_time
        self.gpx_end_time = gpx_end_time

    def __reduce__(self):
        # Pickle with every argument, so that the error survives the trip back
        # from a worker process (video geotagging raises it in one)
        return (
            self.__class__,
            (self.args[0], self.image_time, self.gpx_start_time, self.gpx_end_time),
        )


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


class MapillaryGPSPointsTooFarApartError(MapillaryDescriptionError):
    """
    Two consecutive points of a video are too far apart in time to be stored
    in the uploaded video
    """


class MapillaryZigZagError(MapillaryDescriptionError):
    pass


class MapillaryUploadConnectionError(MapillaryUserError):
    exit_code = 12


class MapillaryUploadTimeoutError(MapillaryUserError):
    exit_code = 13


class MapillaryUploadUnauthorizedError(MapillaryUserError):
    exit_code = 14


class MapillaryMetadataValidationError(MapillaryUserError):
    exit_code = 15
