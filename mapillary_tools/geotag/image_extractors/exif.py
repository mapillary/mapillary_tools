# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import contextlib
import datetime
import os
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import exceptions, exif_read, types, utils
from ...serializer.description import build_capture_time
from .base import BaseImageExtractor


def _invalid_capture_time(capture_time: datetime.datetime) -> Exception:
    return exceptions.MapillaryGeoTaggingError(
        f"Unable to extract timestamp from the image: invalid capture time {capture_time}"
    )


def _capture_unix_time(capture_time: datetime.datetime) -> float:
    """
    The Unix time of the capture time of an image, assuming that a naive one
    is in the local timezone. Some cameras write 0001:01:01 00:00:00 for no
    date, which has no Unix time, and others other dates before 1970 (see
    exif_read.is_valid_capture_time()): raise as for an image with no capture
    time, rather than let geo.as_unix_time() move it to 1970. So for a time
    that the local timezone moves before 1970, or into year 10000, in which
    no capture time can be written.
    """
    if not exif_read.is_valid_capture_time(capture_time):
        raise _invalid_capture_time(capture_time)
    try:
        unix_time = capture_time.timestamp()
        # Raises for a time after year 9999
        datetime.datetime.fromtimestamp(unix_time, datetime.timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise _invalid_capture_time(capture_time)
    if unix_time < 0:
        raise _invalid_capture_time(capture_time)
    return unix_time


def _is_file_time(unix_time: float) -> bool:
    """
    Whether **unix_time** can be the time a file was written: after Unix time
    0, and before year 10000, in which no capture time can be written

    >>> _is_file_time(1714557600.0), _is_file_time(0.0), _is_file_time(-1.0)
    (True, False, False)
    >>> _is_file_time(1e12)
    False
    """
    if unix_time <= 0:
        return False
    try:
        datetime.datetime.fromtimestamp(unix_time, datetime.timezone.utc)
    except (ValueError, OverflowError, OSError):
        return False
    return True


def _earlier_file_time(
    stat: os.stat_result, platform: str = sys.platform
) -> tuple[str, float] | None:
    """
    The earlier of the modification time and the creation time in **stat**,
    and which of them it is ("modification" or "creation"), or None if neither
    can be the time a file was written. The creation time is st_birthtime where
    os.stat() gives it (macOS and BSD, and Windows from Python 3.12), and
    st_ctime on Windows before. On Linux, st_ctime is the time the file's inode
    last changed, not its creation time, so only the modification time is used
    """
    times = [("modification", stat.st_mtime)]
    birthtime = getattr(stat, "st_birthtime", None)
    if birthtime is None and platform == "win32":
        birthtime = stat.st_ctime
    if birthtime is not None:
        times.append(("creation", birthtime))
    file_times = [(name, time) for name, time in times if _is_file_time(time)]
    if not file_times:
        return None
    # Of equal times, the modification time: macOS moves the creation time back
    # to a modification time set before it
    return min(file_times, key=lambda name_time: name_time[1])


def _describe_file_time(
    image_path: Path, file_time: str, unix_time: float
) -> exceptions.MapillaryFileTimeWarning:
    time_str = datetime.datetime.fromtimestamp(
        unix_time, datetime.timezone.utc
    ).isoformat(timespec="seconds")
    return exceptions.MapillaryFileTimeWarning(
        f"No capture time found in the metadata of the image {image_path}: using "
        f"its file {file_time} time {time_str} instead. A downloaded, exported or "
        "copied file has the time of the copy, and images written in one go get "
        "times within seconds of each other, so a sequence of them is uploaded "
        "with the time of the copy or fails as too fast",
        file_time=file_time,
        capture_time=build_capture_time(unix_time),
    )


class ImageEXIFExtractor(BaseImageExtractor):
    """
    Extracts the position and the capture time of an image from its EXIF.

    With **skip_lonlat_error**, an image without a position is extracted at
    (0, 0), for a geotag source that positions it by its capture time (on a
    GPX track, say) instead.

    An image with a position but no capture time is extracted with the earlier
    of its file modification and creation times, and a MapillaryFileTimeWarning
    that says so: process() keeps it only if no other geotag source geotags the
    image. Not with **skip_lonlat_error**, where the capture time positions the
    image, and a file time would position it wrongly, without a word.
    """

    def __init__(self, image_path: Path, skip_lonlat_error: bool = False):
        super().__init__(image_path)
        self.skip_lonlat_error = skip_lonlat_error

    @contextlib.contextmanager
    def _exif_context(self) -> T.Generator[exif_read.ExifReadABC, None, None]:
        with self.image_path.open("rb") as fp:
            yield exif_read.ExifRead(fp)

    def _file_time(self) -> tuple[str, float] | None:
        try:
            stat = self.image_path.stat()
        except OSError:
            return None
        return _earlier_file_time(stat)

    @override
    def extract(self) -> types.ImageMetadata:
        with self._exif_context() as exif:
            lonlat = exif.extract_lon_lat()
            if lonlat is None:
                if not self.skip_lonlat_error:
                    raise exceptions.MapillaryGeoTaggingError(
                        "Unable to extract GPS Longitude or GPS Latitude from the image"
                    )
                lonlat = (0.0, 0.0)
            lon, lat = lonlat

            warnings: list[exceptions.MapillaryProcessWarning] = []
            capture_time = exif.extract_capture_time()
            if capture_time is None:
                if exif.rejected_capture_time is not None:
                    # Say which date was no capture time, as for the only one
                    raise _invalid_capture_time(exif.rejected_capture_time)
                file_time = None if self.skip_lonlat_error else self._file_time()
                if file_time is None:
                    raise exceptions.MapillaryGeoTaggingError(
                        "Unable to extract timestamp from the image"
                    )
                file_time_name, unix_time = file_time
                warnings.append(
                    _describe_file_time(self.image_path, file_time_name, unix_time)
                )
            else:
                unix_time = _capture_unix_time(capture_time)

            image_metadata = types.ImageMetadata(
                filename=self.image_path,
                filesize=utils.get_file_size(self.image_path),
                time=unix_time,
                lat=lat,
                lon=lon,
                alt=exif.extract_altitude(),
                angle=exif.extract_direction(),
                width=exif.extract_width(),
                height=exif.extract_height(),
                MAPOrientation=exif.extract_orientation(),
                MAPDeviceMake=exif.extract_make(),
                MAPDeviceModel=exif.extract_model(),
                MAPCameraUUID=exif.extract_camera_uuid(),
                warnings=warnings,
            )

        return image_metadata
