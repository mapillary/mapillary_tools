# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import contextlib
import datetime
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import exceptions, exif_read, types, utils
from .base import BaseImageExtractor


def _capture_unix_time(capture_time: datetime.datetime) -> float:
    """
    The Unix time of the capture time of an image, assuming that a naive one
    is in the local timezone. Some cameras write 0001:01:01 00:00:00 for no
    date, which has no Unix time: raise as for an image with no capture time,
    rather than let geo.as_unix_time() move it to 1970.
    """
    try:
        return capture_time.timestamp()
    except (ValueError, OverflowError, OSError):
        raise exceptions.MapillaryGeoTaggingError(
            f"Unable to extract timestamp from the image: invalid capture time {capture_time}"
        )


class ImageEXIFExtractor(BaseImageExtractor):
    def __init__(self, image_path: Path, skip_lonlat_error: bool = False):
        super().__init__(image_path)
        self.skip_lonlat_error = skip_lonlat_error

    @contextlib.contextmanager
    def _exif_context(self) -> T.Generator[exif_read.ExifReadABC, None, None]:
        with self.image_path.open("rb") as fp:
            yield exif_read.ExifRead(fp)

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

            capture_time = exif.extract_capture_time()
            if capture_time is None:
                raise exceptions.MapillaryGeoTaggingError(
                    "Unable to extract timestamp from the image"
                )
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
            )

        return image_metadata
