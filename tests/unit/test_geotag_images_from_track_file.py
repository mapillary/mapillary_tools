# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

from pathlib import Path

import pytest
from mapillary_tools import exceptions, types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.geotag_images_from_gpx_file import GeotagImagesFromGPXFile
from mapillary_tools.geotag.geotag_images_from_nmea_file import GeotagImagesFromNMEAFile
from mapillary_tools.geotag.options import SourceOption, SourcePathOption, SourceType

IMAGES = [Path("a.jpg"), Path("b.jpg")]

GPX = (
    '<?xml version="1.0"?>\n'
    '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
    "<trk><trkseg>{}</trkseg></trk></gpx>\n"
)
GPX_POINT = '<trkpt lat="37.0" lon="-122.0"><time>2025-03-14T07:00:00Z</time></trkpt>'

NMEA_RMC = "$GPRMC,081754.14,A,5130.63420,N,00008.06160,W,0.0,0.0,150921,,,A*45\n"
NMEA_GGA = "$GPGGA,081754.14,5130.63420,N,00008.06160,W,1,08,1.0,22.4,M,0.0,M,,*74\n"


def _errors(geotag) -> list[Exception]:
    descs = geotag.to_description(IMAGES)
    assert [d.filename for d in descs] == IMAGES
    assert all(isinstance(d, types.ErrorMetadata) for d in descs)
    return [d.error for d in descs]


def _assert_fails_every_image(geotag, message: str) -> None:
    for error in _errors(geotag):
        assert isinstance(error, exceptions.MapillaryInvalidGPXError)
        assert message in str(error)


class TestGPXFile:
    @pytest.mark.parametrize(
        "content",
        [
            # Cut short, as by an interrupted download
            GPX.format(GPX_POINT * 3)[:-30],
            "This is not a GPX file.\n",
        ],
    )
    def test_a_file_that_is_no_gpx_fails_every_image(self, tmp_path, content):
        gpx = tmp_path / "track.gpx"
        gpx.write_text(content)

        _assert_fails_every_image(
            GeotagImagesFromGPXFile(gpx),
            "track.gpx is not a valid GPX file. Replace it with a valid GPX file.",
        )

    def test_a_missing_file_fails_every_image(self, tmp_path):
        _assert_fails_every_image(
            GeotagImagesFromGPXFile(tmp_path / "missing.gpx"), "GPX file not found"
        )

    def test_a_track_without_timestamps_fails_every_image(self, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text(GPX.format('<trkpt lat="37.0" lon="-122.0"></trkpt>'))

        _assert_fails_every_image(
            GeotagImagesFromGPXFile(gpx),
            "track.gpx has no track point with a time that can be read: "
            "its track points have no <time>",
        )

    def test_a_valid_file_is_read(self, tmp_path):
        gpx = tmp_path / "track.gpx"
        gpx.write_text(GPX.format(GPX_POINT))

        geotag = GeotagImagesFromGPXFile(gpx)

        assert geotag.track_error is None
        assert [(p.lat, p.lon) for p in geotag.points] == [(37.0, -122.0)]


class TestNMEAFile:
    @pytest.mark.parametrize(
        "content",
        [
            # The checksum does not match
            NMEA_RMC.replace("*45", "*00") + NMEA_GGA,
            # Void, as a receiver writes before its first fix: no time or date
            "$GPRMC,,V,,,,,,,,,,N*53\n" + NMEA_GGA,
            # No RMC sentence to give the date
            NMEA_GGA,
        ],
    )
    def test_a_file_that_fails_to_parse_fails_every_image(self, tmp_path, content):
        nmea = tmp_path / "track.nmea"
        nmea.write_text(content)

        # Not a valid NMEA file, or none of its points timestamped if the
        # parser skips the sentences it cannot time
        _assert_fails_every_image(GeotagImagesFromNMEAFile(nmea), "track.nmea")

    def test_a_file_without_sentences_fails_every_image(self, tmp_path):
        nmea = tmp_path / "track.nmea"
        nmea.write_text("This is not a GPX file.\n")

        _assert_fails_every_image(
            GeotagImagesFromNMEAFile(nmea), "No timestamped points found"
        )

    def test_a_missing_file_fails_every_image(self, tmp_path):
        _assert_fails_every_image(
            GeotagImagesFromNMEAFile(tmp_path / "missing.nmea"), "NMEA file not found"
        )

    def test_a_malformed_sentence_is_skipped(self, tmp_path):
        """It failed every image"""
        nmea = tmp_path / "track.nmea"
        nmea.write_text(NMEA_RMC + NMEA_GGA.replace("$GPGGA", "$GLGGA") + NMEA_GGA)

        geotag = GeotagImagesFromNMEAFile(nmea)

        assert geotag.track_error is None
        assert len(geotag.points) == 1

    def test_a_valid_file_is_read(self, tmp_path):
        nmea = tmp_path / "track.nmea"
        nmea.write_text(NMEA_RMC + NMEA_GGA)

        geotag = GeotagImagesFromNMEAFile(nmea)

        assert geotag.track_error is None
        assert len(geotag.points) == 1


def test_the_next_source_does_not_geotag_the_images_of_a_missing_gpx(tmp_path):
    """
    The GPX was given to geotag the images from, and a mistyped path must not
    pass unnoticed because the next source geotags them instead
    """
    images = sorted(
        Path(__file__).resolve().parent.parent.joinpath("data", "images").glob("*.JPG")
    )
    assert images
    options = [
        SourceOption(
            SourceType.GPX,
            source_path=SourcePathOption(source_path=tmp_path / "missing.gpx"),
        ),
        SourceOption(SourceType.EXIF),
    ]

    descs = factory.process(images, options)

    assert sorted(d.filename for d in descs) == images
    for desc in descs:
        assert isinstance(desc, types.ErrorMetadata)
        assert isinstance(desc.error, exceptions.MapillaryInvalidGPXError)
