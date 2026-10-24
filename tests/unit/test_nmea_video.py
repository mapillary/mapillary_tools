# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Geotagging videos from NMEA files, which are placed on the videos as GPX files
are. NMEA files geotagged no videos: the videos got no description at all.
"""

from __future__ import annotations

import datetime
import logging
import pickle
from pathlib import Path

import pynmea2
import pytest
from mapillary_tools import exceptions, types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.geotag_videos_from_nmea import GeotagVideosFromNMEA
from mapillary_tools.geotag.options import (
    InterpolationOption,
    SourceOption,
    SourcePathOption,
    SourceType,
    VideoSyncOption,
)
from mapillary_tools.geotag import geotag_images_from_nmea_file
from mapillary_tools.geotag.video_extractors import nmea as nmea_extractor
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor
from mapillary_tools.geotag.video_extractors.nmea import NMEAVideoExtractor

_DATA = Path(__file__).resolve().parent.parent.joinpath("data")

# No GPS of its own, and 5.76 seconds long
NO_GPS_VIDEO = _DATA.joinpath("videos", "sample-5s.mp4")
# GPS of its own, recorded from 2019-11-18T23:44:42.59Z to 23:44:54.64Z
GPS_VIDEO = _DATA.joinpath("gopro_data", "max-360mode.mp4")

# Shortly before the GPS track of GPS_VIDEO starts
START = datetime.datetime(2019, 11, 18, 23, 44, 40, tzinfo=datetime.timezone.utc)


def _track(seconds: int, start: datetime.datetime):
    """A point every second, heading north at 10 m/s, 12 m high"""
    for i in range(seconds + 1):
        yield start + datetime.timedelta(seconds=i), 37.0 + i * 10 / 111_320, 12.0


def _write_gpx(path: Path, seconds: int, start: datetime.datetime = START) -> Path:
    points = "".join(
        f'<trkpt lat="{lat:.9f}" lon="-122.0"><ele>{alt}</ele>'
        f"<time>{time.strftime('%Y-%m-%dT%H:%M:%SZ')}</time></trkpt>"
        for time, lat, alt in _track(seconds, start)
    )
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{points}</trkseg></trk></gpx>\n"
    )
    return path


def _write_nmea(
    path: Path,
    seconds: int,
    start: datetime.datetime = START,
    gga_first: bool = False,
) -> Path:
    """
    The track of _write_gpx(), as RMC and GGA sentences, the GGA sentence of
    each fix first or last
    """
    lines = []
    for time, lat, alt in _track(seconds, start):
        hhmmss = time.strftime("%H%M%S.00")
        lat_field = f"{int(lat):02d}{(lat - int(lat)) * 60:010.7f}"
        lon_field = "12200.0000000"
        lines.append(
            pynmea2.RMC(
                "GP",
                "RMC",
                (hhmmss, "A", lat_field, "N", lon_field, "W", "19.4", "0.0")
                + (time.strftime("%d%m%y"), "", "", "A"),
            )
        )
        lines.append(
            pynmea2.GGA(
                "GP",
                "GGA",
                (hhmmss, lat_field, "N", lon_field, "W", "1", "08", "1.0")
                + (f"{alt:.1f}", "M", "0.0", "M", "", ""),
            )
        )
        if gga_first:
            lines[-2:] = lines[-1:-3:-1]
    path.write_text("".join(f"{line}\r\n" for line in lines))
    return path


def _points(extractor: GPXVideoExtractor):
    return [
        (p.time, p.lat, p.lon, p.alt, p.get_unix_time())
        for p in extractor.extract().points
    ]


class TestPlacedAsAGPX:
    @pytest.mark.parametrize(
        "video, seconds, kwargs",
        [
            # synced by the GPS clock of the video, and clipped to it, in process
            (GPS_VIDEO, 20, {"clip_to_video": True}),
            # started with the video
            (
                GPS_VIDEO,
                20,
                {"interpolation": InterpolationOption(use_gpx_start_time=True)},
            ),
            # moved by the offset
            (GPS_VIDEO, 20, {"interpolation": InterpolationOption(offset_time=2)}),
            # assumed to start with a video without GPS
            (NO_GPS_VIDEO, 6, {}),
            # placed by the start time of a video without GPS, in sampling
            (
                NO_GPS_VIDEO,
                60,
                {
                    "video_sync": VideoSyncOption(
                        start_time=START.timestamp() + 30, duration_ratio=2
                    )
                },
            ),
        ],
    )
    def test_the_track_is_placed_as_from_a_gpx(self, tmp_path, video, seconds, kwargs):
        gpx = _write_gpx(tmp_path / "track.gpx", seconds)
        nmea = _write_nmea(tmp_path / "track.nmea", seconds)

        from_gpx = _points(GPXVideoExtractor(video, gpx, **kwargs))
        from_nmea = _points(NMEAVideoExtractor(video, nmea, **kwargs))

        assert from_nmea
        assert len(from_nmea) == len(from_gpx)
        for nmea_point, gpx_point in zip(from_nmea, from_gpx):
            assert nmea_point == pytest.approx(gpx_point, abs=1e-6)

    def test_a_track_across_midnight_is_placed_as_from_a_gpx(self, tmp_path):
        """
        Its first fix after midnight, logged before the RMC sentence with its
        date, was dated a day early, and the video got a track of a day
        """
        start = datetime.datetime(
            2019, 11, 18, 23, 59, 57, tzinfo=datetime.timezone.utc
        )
        gpx = _write_gpx(tmp_path / "track.gpx", 6, start)
        nmea = _write_nmea(tmp_path / "track.nmea", 6, start, gga_first=True)

        from_gpx = _points(GPXVideoExtractor(NO_GPS_VIDEO, gpx))
        from_nmea = _points(NMEAVideoExtractor(NO_GPS_VIDEO, nmea))

        assert len(from_nmea) == len(from_gpx) == 7
        for nmea_point, gpx_point in zip(from_nmea, from_gpx):
            assert nmea_point == pytest.approx(gpx_point, abs=1e-6)

    def test_a_malformed_sentence_is_skipped(self, tmp_path):
        """It failed the whole file"""
        gpx = _write_gpx(tmp_path / "track.gpx", 6)
        nmea = _write_nmea(tmp_path / "track.nmea", 6)
        lines = nmea.read_text().splitlines()
        lines.insert(5, lines[4][:-2] + "00")
        nmea.write_text("\r\n".join(lines))

        from_gpx = _points(GPXVideoExtractor(NO_GPS_VIDEO, gpx))
        from_nmea = _points(NMEAVideoExtractor(NO_GPS_VIDEO, nmea))

        assert len(from_nmea) == len(from_gpx) == 7
        for nmea_point, gpx_point in zip(from_nmea, from_gpx):
            assert nmea_point == pytest.approx(gpx_point, abs=1e-6)

    def test_messages_name_the_nmea_file(self, tmp_path):
        nmea = _write_nmea(tmp_path / "track.nmea", seconds=60)

        with pytest.raises(exceptions.MapillaryGPXVideoStartUnknownError) as excinfo:
            NMEAVideoExtractor(
                NO_GPS_VIDEO, nmea, video_sync=VideoSyncOption()
            ).extract()

        assert str(excinfo.value).startswith(f"The NMEA track in {nmea} lasts")


class TestInvalidNMEAFile:
    @pytest.mark.parametrize(
        "content",
        [
            # not text
            b"\xca\xfe\xba\xbe" * 100,
            # a wrong checksum
            b"$GPRMC,024636.00,A,3735.30670,N,12220.25810,W,0.0,0.0,221222,,,A*00\r\n",
            # a malformed time
            b"$GPRMC,024636.00,A,3735.30670,N,12220.25810,W,0.0,0.0,221222,,,A*47\r\n"
            b"$GPGGA,0246,3735.30670,N,12220.25810,W,1,08,1.0,0.0,M,0.0,M,,*64\r\n",
        ],
    )
    def test_it_is_reported_as_invalid(self, tmp_path, content):
        nmea = tmp_path / "track.nmea"
        nmea.write_bytes(content)

        with pytest.raises(exceptions.MapillaryInvalidGPXError) as excinfo:
            NMEAVideoExtractor(GPS_VIDEO, nmea).extract()

        assert "track.nmea is not a valid NMEA file" in str(excinfo.value)


class TestNMEAFileWithoutDatedFixes:
    @pytest.mark.parametrize(
        "content, warning",
        [
            # a GGA sentence, and no RMC sentence to give its date
            (
                b"$GPGGA,024636.00,3735.30670,N,12220.25810,W,1,08,1.0,0.0,M,0.0,M,,*4F\r\n",
                "as no RMC sentence gives their date",
            ),
            # an RMC sentence cut short, with no date, which is skipped
            (b"$GPRMC,024636.00,A,3735.30670,N,12220.25810,W,0.0*07\r\n", None),
        ],
    )
    def test_no_points_are_read(self, tmp_path, caplog, content, warning):
        nmea = tmp_path / "track.nmea"
        nmea.write_bytes(content)

        with caplog.at_level(logging.WARNING):
            points = NMEAVideoExtractor(GPS_VIDEO, nmea)._read_gpx_points()

        assert points == []
        if warning is None:
            assert not caplog.text
        else:
            assert warning in caplog.text


class TestGeotagVideosFromNMEA:
    def test_the_nmea_file_beside_the_video_is_found(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(GPS_VIDEO.read_bytes())
        _write_nmea(tmp_path / "video.nmea", seconds=20)

        [metadata] = GeotagVideosFromNMEA(num_processes=0).to_description([video])

        assert isinstance(metadata, types.VideoMetadata)
        assert metadata.points

    def test_a_missing_nmea_file_is_reported(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(GPS_VIDEO.read_bytes())

        [metadata] = GeotagVideosFromNMEA(num_processes=0).to_description([video])

        assert isinstance(metadata, types.ErrorMetadata)
        assert isinstance(metadata.error, exceptions.MapillaryVideoGPSNotFoundError)
        assert str(metadata.error) == "NMEA file not found for video"

    def test_process_geotags_videos_from_nmea(self, tmp_path):
        nmea = _write_nmea(tmp_path / "track.nmea", seconds=20)

        [metadata] = factory.process(
            [GPS_VIDEO],
            [
                SourceOption(
                    SourceType.NMEA,
                    source_path=SourcePathOption(source_path=nmea),
                    num_processes=0,
                )
            ],
        )

        assert isinstance(metadata, types.VideoMetadata)
        assert metadata.points


class TestNMEAFileReadOnce:
    def _videos(self, tmp_path: Path, count: int) -> list[Path]:
        videos = []
        for i in range(count):
            video = tmp_path / f"video{i}.mp4"
            video.write_bytes(GPS_VIDEO.read_bytes())
            videos.append(video)
        return videos

    def test_videos_geotagged_from_one_file_read_it_once(
        self, tmp_path, caplog, monkeypatch
    ):
        """Each video read it again, in its own process, and warned again"""
        nmea = _write_nmea(tmp_path / "track.nmea", seconds=20)
        with nmea.open("ab") as f:
            f.write(b"$GPGGA,0246\r\n")
        reads = []
        read = geotag_images_from_nmea_file._read_nmea_data
        monkeypatch.setattr(
            geotag_images_from_nmea_file,
            "_read_nmea_data",
            lambda nmea_file, data: reads.append(nmea_file) or read(nmea_file, data),
        )

        with caplog.at_level(logging.WARNING):
            metadatas = GeotagVideosFromNMEA(
                source_path=SourcePathOption(source_path=nmea), num_processes=0
            ).to_description(self._videos(tmp_path, 3))

        assert all(
            isinstance(metadata, types.VideoMetadata) and metadata.points
            for metadata in metadatas
        )
        assert len(reads) == 1
        assert caplog.text.count("Skipping 1 of the") == 1

    def test_the_track_is_read_before_the_videos_are_geotagged(
        self, tmp_path, monkeypatch
    ):
        """
        In a process of a pool, which gets the extractor pickled, the track
        is not read again
        """
        nmea = _write_nmea(tmp_path / "track.nmea", seconds=20)
        [extractor] = GeotagVideosFromNMEA(
            source_path=SourcePathOption(source_path=nmea), num_processes=0
        )._generate_video_extractors([GPS_VIDEO])
        extractor = pickle.loads(pickle.dumps(extractor))

        def read_again(nmea_file):
            raise AssertionError(f"{nmea_file} read again")

        monkeypatch.setattr(nmea_extractor, "get_lat_lon_time_from_nmea", read_again)

        metadata = extractor.extract()
        assert metadata.points

    def test_an_invalid_file_is_reported_for_every_video(self, tmp_path):
        nmea = tmp_path / "track.nmea"
        nmea.write_bytes(b"\xca\xfe\xba\xbe" * 100)

        metadatas = GeotagVideosFromNMEA(
            source_path=SourcePathOption(source_path=nmea), num_processes=0
        ).to_description(self._videos(tmp_path, 2))

        for metadata in metadatas:
            assert isinstance(metadata, types.ErrorMetadata)
            assert isinstance(metadata.error, exceptions.MapillaryInvalidGPXError)
            assert "track.nmea is not a valid NMEA file" in str(metadata.error)
