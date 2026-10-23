# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

from pathlib import Path

import pytest
from mapillary_tools import exceptions, sample_video
from mapillary_tools.geotag.factory import parse_source_option, parse_source_options
from mapillary_tools.geotag.options import SourceType
from mapillary_tools.types import FileType


class TestParseSourceOption:
    def test_source_types(self):
        assert [o.source for o in parse_source_option("gpx")] == [SourceType.GPX]
        assert [o.source for o in parse_source_option("gopro_videos")] == [
            SourceType.GOPRO
        ]
        assert [o.source for o in parse_source_option("exif,native")] == [
            SourceType.EXIF,
            SourceType.NATIVE,
        ]
        assert [o.source for o in parse_source_option('{"source": "nmea"}')] == [
            SourceType.NMEA
        ]

    @pytest.mark.parametrize("source", ["foo", "gpx,foo", "foo,gpx"])
    def test_unknown_source_type_names_the_supported_ones(self, source):
        with pytest.raises(exceptions.MapillaryBadParameterError) as excinfo:
            parse_source_option(source)

        message = str(excinfo.value)
        assert "'foo'" in message
        assert ", ".join(s.value for s in SourceType) in message
        assert "(aliases: blackvue_videos, gopro_videos, exiftool)" in message

    def test_unknown_key_is_named(self):
        with pytest.raises(exceptions.MapillaryBadParameterError) as excinfo:
            parse_source_option('{"source": "gpx", "path": "track.gpx"}')

        assert "'path' was unexpected" in str(excinfo.value)

    @pytest.mark.parametrize(
        "source",
        [
            '{"source": "foo"}',
            '{"path": "track.gpx"}',
            '{"source": "gpx", "filetypes": ["mp4"]}',
            '{"source": "gpx", "interpolation_offset_time": "1s"}',
            "123",
        ],
    )
    def test_invalid_json_source(self, source):
        with pytest.raises(exceptions.MapillaryBadParameterError):
            parse_source_option(source)

    def test_video_geotag_source(self):
        with pytest.raises(exceptions.MapillaryBadParameterError) as excinfo:
            parse_source_options(
                geotag_source=[], video_geotag_source=["foo"], geotag_source_path=None
            )

        assert "(aliases: blackvue_videos, gopro_videos, exiftool, video)" in str(
            excinfo.value
        )

    @pytest.mark.parametrize(
        "source", ["video", '{"source": "video"}', "native", "video,native"]
    )
    def test_video_reads_videos_natively(self, source):
        options = parse_source_options(
            geotag_source=[], video_geotag_source=[source], geotag_source_path=None
        )

        for option in options:
            assert option.source is SourceType.NATIVE
            assert option.filetypes == {FileType.VIDEO}

    @pytest.mark.parametrize(
        "source, filetype",
        [
            ("gopro", FileType.GOPRO),
            ("gopro_videos", FileType.GOPRO),
            ('{"source": "gopro", "pattern": "%f"}', FileType.GOPRO),
            ("camm", FileType.CAMM),
            ("blackvue", FileType.BLACKVUE),
            ("blackvue_videos", FileType.BLACKVUE),
        ],
    )
    def test_legacy_sources_read_videos_of_their_type(self, source, filetype):
        [option] = parse_source_options(
            geotag_source=[], video_geotag_source=[source], geotag_source_path=None
        )

        assert option.source is SourceType.NATIVE
        assert option.filetypes == {filetype}

    def test_legacy_sources_of_images_are_kept(self):
        options = parse_source_options(
            geotag_source=["gopro", "blackvue_videos", "camm"],
            video_geotag_source=[],
            geotag_source_path=None,
        )

        assert [(o.source, o.filetypes) for o in options] == [
            (SourceType.GOPRO, None),
            (SourceType.BLACKVUE, None),
            (SourceType.CAMM, None),
        ]

    @pytest.mark.parametrize("source", ["video", '{"source": "video"}'])
    def test_video_is_not_an_image_source(self, source):
        with pytest.raises(exceptions.MapillaryBadParameterError):
            parse_source_options(
                geotag_source=[source], video_geotag_source=[], geotag_source_path=None
            )

    def test_video_process_samples_by_legacy_source(self, tmp_path: Path):
        [option] = sample_video._parse_video_sources(None, None, ["gopro"], tmp_path)

        assert option.source is SourceType.NATIVE
        assert option.filetypes == {FileType.GOPRO}

    def test_video_process(self, tmp_path: Path):
        with pytest.raises(exceptions.MapillaryBadParameterError):
            sample_video._parse_video_sources(["foo"], None, None, tmp_path)
