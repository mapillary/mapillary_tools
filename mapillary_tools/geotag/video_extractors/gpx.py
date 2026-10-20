# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import dataclasses
import enum
import logging
import statistics
import sys
import typing as T
from pathlib import Path

import gpxpy

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import exceptions, geo, types, utils
from ..utils import parse_gpx
from .base import BaseVideoExtractor
from .native import NativeVideoExtractor


LOG = logging.getLogger(__name__)

# A GPX track and the video it is synced against should overlap in time. Warn
# above a day, which no legitimate pairing needs and an epoch mix-up exceeds by
# orders of magnitude.
_IMPLAUSIBLE_OFFSET_SECONDS = 24 * 3600

# A GPS clock that runs this much faster than the video clock is a timelapse.
# Normal videos stay well below it, although over a few seconds of GPS
# timestamped once per block the estimate can be 20% off
_MIN_TIMELAPSE_RATE = 1.5


class SyncMode(enum.Enum):
    # Sync by video GPS timestamps if found, otherwise rebase
    SYNC = "sync"
    # Sync by video GPS timestamps, and throw if not found
    STRICT_SYNC = "strict_sync"
    # Rebase all GPX timestamps to start from 0
    REBASE = "rebase"


@dataclasses.dataclass(frozen=True)
class VideoClock:
    """
    Maps between the video time and the Unix time of the GPS clock in the video

    >>> clock = VideoClock(video_time=2.0, unix_time=1000.0)
    >>> clock.to_video_time(1030.0)
    32.0
    >>> timelapse = VideoClock(video_time=2.0, unix_time=1000.0, rate=15.0)
    >>> timelapse.to_video_time(1030.0)
    4.0
    >>> timelapse.to_unix_time(4.0)
    1030.0
    """

    video_time: float
    unix_time: float
    # GPS seconds per video second: 1 unless the video is a timelapse
    rate: float = 1.0

    def to_video_time(self, unix_time: float) -> float:
        return self.video_time + (unix_time - self.unix_time) / self.rate

    def to_unix_time(self, video_time: float) -> float:
        return self.unix_time + (video_time - self.video_time) * self.rate


class GPXVideoExtractor(BaseVideoExtractor):
    def __init__(
        self, video_path: Path, gpx_path: Path, sync_mode: SyncMode = SyncMode.SYNC
    ):
        self.video_path = video_path
        self.gpx_path = gpx_path
        self.sync_mode = sync_mode

    @override
    def extract(self) -> types.VideoMetadata:
        try:
            gpx_tracks = parse_gpx(self.gpx_path)
        except (OSError, UnicodeError, gpxpy.gpx.GPXException) as ex:
            raise exceptions.MapillaryInvalidGPXError(
                f"{self.gpx_path.name} is not a valid GPX file. "
                "Replace it with a valid GPX file."
            ) from ex

        if 1 < len(gpx_tracks):
            LOG.warning(
                f"Found {len(gpx_tracks)} tracks in the GPX file {self.gpx_path}. Will merge points in all the tracks as a single track for interpolation"
            )

        gpx_points: T.Sequence[geo.Point] = sum(gpx_tracks, [])

        try:
            native_video_metadata, noisy = self._extract_native_video_metadata()
        except exceptions.MapillaryVideoGPSUnusableError as ex:
            # The GPX replaces the video's own GPS, so GPS that is missing,
            # empty or too noisy must not reject the video
            if self.sync_mode is SyncMode.STRICT_SYNC:
                raise ex
            self._rebase_times(gpx_points)
            return types.VideoMetadata(
                filename=self.video_path,
                filesize=utils.get_file_size(self.video_path),
                filetype=types.FileType.VIDEO,
                points=gpx_points,
            )

        clock: VideoClock | None = None
        if self.sync_mode is not SyncMode.REBASE:
            clock = self._read_video_clock(native_video_metadata.points)

        if clock is not None and gpx_points:
            offset = gpx_points[0].time - clock.to_unix_time(0)
            if abs(offset) > _IMPLAUSIBLE_OFFSET_SECONDS:
                if noisy and self.sync_mode is SyncMode.SYNC:
                    # GPS rejected as noise may not have GPS time yet: GoPro
                    # stamps a placeholder date until it acquires it. That GPS
                    # is what the GPX replaces, so do not let its clock place
                    # the GPX days away from the video
                    LOG.warning(
                        "The GPS clock of %s, whose GPS was rejected as noise, is %.1f days away from %s. "
                        "Syncing the GPX from the start of the video instead",
                        self.video_path,
                        abs(offset) / 86400,
                        self.gpx_path,
                    )
                    clock = None
                else:
                    LOG.warning(
                        "Syncing %s against %s requires an offset of %.0f seconds (%.1f days). "
                        "The GPX file probably does not belong to this video",
                        self.video_path,
                        self.gpx_path,
                        offset,
                        offset / 86400,
                    )

        if clock is None:
            self._rebase_times(gpx_points)
        else:
            if clock.rate != 1.0:
                LOG.info(
                    "The GPS clock in %s runs %.1f times faster than the video (timelapse). Syncing %s accordingly",
                    self.video_path,
                    clock.rate,
                    self.gpx_path,
                )
            for p in gpx_points:
                p.time = clock.to_video_time(p.time)

        return dataclasses.replace(native_video_metadata, points=gpx_points)

    def _extract_native_video_metadata(self) -> tuple[types.VideoMetadata, bool]:
        """
        Extract the video metadata, and whether its GPS was rejected as noise
        """
        try:
            return NativeVideoExtractor(self.video_path).extract(), False
        except exceptions.MapillaryGPSNoiseError:
            # The GPX replaces the video's own GPS, which is then only needed
            # for make/model and a clock to sync against. Noisy points are
            # never published
            metadata = NativeVideoExtractor(
                self.video_path, filter_noisy_points=False
            ).extract()
            return metadata, True

    @classmethod
    def _rebase_times(cls, points: T.Sequence[geo.Point], offset: float = 0.0) -> None:
        """
        Rebase point times to start from **offset**
        """
        if points:
            first_timestamp = points[0].time
            for p in points:
                p.time = (p.time - first_timestamp) + offset

    @classmethod
    def _read_video_clock(
        cls, video_gps_points: T.Sequence[geo.Point]
    ) -> VideoClock | None:
        """
        Read the GPS clock from the video GPS points, or None if they have no timestamps

        >>> GPXVideoExtractor._read_video_clock([]) is None
        True
        >>> point = geo.Point(time=5, lat=1, lon=1, alt=None, angle=None)
        >>> GPXVideoExtractor._read_video_clock([point]) is None
        True
        """
        # (video time, Unix time) pairs
        pairs: list[tuple[float, float]] = []

        for p in video_gps_points:
            # Video GPS timestamps are stored in whatever epoch their container
            # uses (CAMM records GPS time, GoPro records Unix time), so go
            # through get_unix_time(), which also skips zero/invalid timestamps
            unix_time = p.get_unix_time()
            if unix_time is None:
                continue
            if pairs and unix_time == pairs[-1][1]:
                # GoPro GPS5 stamps a whole block (~1s) of points with one
                # timestamp. Keep the first point of the block
                continue
            pairs.append((p.time, unix_time))

        if not pairs:
            return None

        # Anchored at its own video time, which is not 0 when the video's GPS
        # starts late (e.g. GoPro drops noisy fixes at the start of a recording)
        video_time, unix_time = pairs[0]

        rate = cls._estimate_clock_rate(pairs)
        # One timestamp far off (e.g. a placeholder date before GPS time is
        # acquired) can pull the least-squares slope far off, so a timelapse
        # must show in the median step between neighbouring pairs too. That is
        # too coarse to measure the rate, but not to tell a timelapse from a
        # normal video
        step_rate = cls._median_step_rate(pairs)
        if (
            rate is not None
            and _MIN_TIMELAPSE_RATE < rate
            and step_rate is not None
            and _MIN_TIMELAPSE_RATE < step_rate
        ):
            return VideoClock(video_time=video_time, unix_time=unix_time, rate=rate)

        return VideoClock(video_time=video_time, unix_time=unix_time)

    @classmethod
    def _estimate_clock_rate(
        cls, pairs: T.Sequence[tuple[float, float]]
    ) -> float | None:
        """
        Least-squares slope of the Unix time over the video time, or None if the
        pairs span less than a second of video

        >>> GPXVideoExtractor._estimate_clock_rate([(0, 100), (1, 115), (2, 130)])
        15.0
        >>> GPXVideoExtractor._estimate_clock_rate([(0, 100), (0.5, 107.5)]) is None
        True
        """
        if len(pairs) < 2 or pairs[-1][0] - pairs[0][0] < 1.0:
            return None

        n = len(pairs)
        mean_video_time = sum(v for v, _ in pairs) / n
        mean_unix_time = sum(u for _, u in pairs) / n
        covariance = sum((v - mean_video_time) * (u - mean_unix_time) for v, u in pairs)
        variance = sum((v - mean_video_time) ** 2 for v, _ in pairs)
        return covariance / variance

    @classmethod
    def _median_step_rate(cls, pairs: T.Sequence[tuple[float, float]]) -> float | None:
        """
        Median rate of the GPS clock between neighbouring pairs, or None if
        there are none

        >>> pairs = [(0, 100), (1, 101), (2, 102), (3, 140), (4, 141)]
        >>> GPXVideoExtractor._median_step_rate(pairs)
        1.0
        """
        steps = [
            (u2 - u1) / (v2 - v1)
            for (v1, u1), (v2, u2) in zip(pairs, pairs[1:])
            if v1 < v2
        ]
        return statistics.median(steps) if steps else None
