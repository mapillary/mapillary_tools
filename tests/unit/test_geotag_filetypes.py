# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
--filetypes limits processing to the videos of the types given. The type of a
video is known only once it is read, so a video of another type is left out
once a source finds out, and no later source reads it.
"""

from __future__ import annotations

import typing as T
from pathlib import Path

import pytest
from mapillary_tools import exceptions, types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import SourceOption, SourceType
from mapillary_tools.geotag.video_extractors.native import NativeVideoExtractor

DATA = Path(__file__).parent.parent / "data"

NOT_FOUND = exceptions.MapillaryVideoGPSNotFoundError(
    "No GPS data found from the video"
)

Outcome = T.Union[Exception, types.FileType]


def _run_chain(
    monkeypatch: pytest.MonkeyPatch,
    options: T.Sequence[SourceOption],
    outcomes: dict[SourceType, Outcome],
    filetypes: set[types.FileType] | None,
) -> tuple[list[types.MetadataOrError], list[SourceType]]:
    """
    Run factory.process() on one video with --filetypes **filetypes**, which
    every option is limited to, as process_geotag_properties() does. Each source
    that geotags videos is replaced by a stub that reports outcomes[source]: an
    error, or the file type it read the video as. Returns the results and the
    sources that read the video.
    """
    called: list[SourceType] = []

    class StubGeotag:
        def __init__(self, source: SourceType):
            self.source = source

        def to_description(self, paths):
            called.append(self.source)
            outcome = outcomes[self.source]
            if isinstance(outcome, types.FileType):
                return [
                    types.VideoMetadata(filename=path, filetype=outcome, points=[])
                    for path in paths
                ]
            return [
                types.describe_error_metadata(
                    outcome, filename=path, filetype=types.FileType.VIDEO
                )
                for path in paths
            ]

    def build_video_geotag(option: SourceOption):
        if option.source is SourceType.EXIF:
            return None
        return StubGeotag(option.source)

    monkeypatch.setattr(factory, "_build_video_geotag", build_video_geotag)
    for option in options:
        option.filetypes = types.combine_filetype_filters(option.filetypes, filetypes)
    results = factory.process([Path("/tmp/video.mp4")], options, filetypes)
    return results, called


def _options(*sources: SourceType) -> list[SourceOption]:
    return [SourceOption(source) for source in sources]


DEFAULT_CHAIN = [SourceType.NATIVE, SourceType.EXIFTOOL_RUNTIME]
GOPRO = {types.FileType.GOPRO}


class TestProcess:
    def test_video_of_another_type_is_left_out(self, monkeypatch):
        """ExifTool processed it after the native reader, whatever its type"""
        results, called = _run_chain(
            monkeypatch,
            _options(*DEFAULT_CHAIN),
            {
                SourceType.NATIVE: NOT_FOUND,
                SourceType.EXIFTOOL_RUNTIME: types.FileType.VIDEO,
            },
            GOPRO,
        )
        assert results == []
        assert called == [SourceType.NATIVE]

    def test_video_read_as_another_type_is_left_out(self, monkeypatch):
        results, _ = _run_chain(
            monkeypatch,
            _options(SourceType.GPX),
            {SourceType.GPX: types.FileType.BLACKVUE},
            GOPRO,
        )
        assert results == []

    @pytest.mark.parametrize("filetype", [types.FileType.GOPRO, types.FileType.VIDEO])
    def test_video_of_a_type_asked_for_or_unknown_is_kept(self, monkeypatch, filetype):
        """
        A GPX or ExifTool reads a video without telling its type, which may well
        be one asked for
        """
        results, _ = _run_chain(
            monkeypatch,
            _options(SourceType.EXIFTOOL_RUNTIME),
            {SourceType.EXIFTOOL_RUNTIME: filetype},
            GOPRO,
        )
        [result] = results
        assert isinstance(result, types.VideoMetadata)
        assert result.filetype is filetype

    def test_an_earlier_error_is_not_reported(self, monkeypatch):
        results, _ = _run_chain(
            monkeypatch,
            _options(SourceType.GPX, SourceType.NATIVE),
            {SourceType.GPX: NOT_FOUND, SourceType.NATIVE: NOT_FOUND},
            GOPRO,
        )
        assert results == []

    def test_gps_of_a_type_asked_for_that_is_unusable_is_reported(self, monkeypatch):
        noise = exceptions.MapillaryGPSNoiseError("GPS is too noisy")
        results, _ = _run_chain(
            monkeypatch,
            _options(*DEFAULT_CHAIN),
            {
                SourceType.NATIVE: noise,
                SourceType.EXIFTOOL_RUNTIME: types.FileType.VIDEO,
            },
            GOPRO,
        )
        [result] = results
        assert isinstance(result, types.ErrorMetadata)
        assert result.error is noise

    @pytest.mark.parametrize("filetypes", [None, {types.FileType.VIDEO}])
    def test_any_video_type(self, monkeypatch, filetypes):
        results, called = _run_chain(
            monkeypatch,
            _options(*DEFAULT_CHAIN),
            {
                SourceType.NATIVE: NOT_FOUND,
                SourceType.EXIFTOOL_RUNTIME: types.FileType.VIDEO,
            },
            filetypes,
        )
        [result] = results
        assert isinstance(result, types.VideoMetadata)
        assert called == DEFAULT_CHAIN

    @pytest.mark.parametrize(
        "filetypes", [None, {types.FileType.GOPRO, types.FileType.BLACKVUE}]
    )
    def test_the_filetypes_of_a_source_leave_the_video_to_the_next(
        self, monkeypatch, filetypes
    ):
        """
        A source limited to some types by its own filetypes found only that the
        video is not of those
        """
        results, called = _run_chain(
            monkeypatch,
            [
                SourceOption(SourceType.NATIVE, filetypes=GOPRO),
                SourceOption(SourceType.EXIFTOOL_RUNTIME),
            ],
            {
                SourceType.NATIVE: NOT_FOUND,
                SourceType.EXIFTOOL_RUNTIME: types.FileType.VIDEO,
            },
            filetypes,
        )
        [result] = results
        assert isinstance(result, types.VideoMetadata)
        assert called == DEFAULT_CHAIN

    @pytest.mark.parametrize(
        "filetypes", [None, GOPRO, {types.FileType.GOPRO, types.FileType.BLACKVUE}]
    )
    def test_video_of_a_type_asked_for_that_no_source_can_read_is_reported(
        self, filetypes
    ):
        """
        It was left out, as if it had not been there, when --filetypes was
        given. Its type is read to tell, by the native reader
        """
        video = DATA / "gopro_data" / "max-360mode.mp4"
        [result] = _process_without_stubs([video], _options(SourceType.EXIF), filetypes)
        assert isinstance(result, types.ErrorMetadata)
        assert result.filename == video
        assert "cannot geotag videos" in str(result.error)

    @pytest.mark.parametrize(
        ("video", "filetypes"),
        [
            (DATA / "videos" / "sample-5s.mp4", GOPRO),
            (DATA / "gopro_data" / "max-360mode.mp4", {types.FileType.BLACKVUE}),
        ],
    )
    def test_video_of_another_type_that_no_source_can_read_is_left_out(
        self, video, filetypes
    ):
        results = _process_without_stubs([video], _options(SourceType.EXIF), filetypes)
        assert results == []


def _blackvue_source_and_default_image_sources() -> list[SourceOption]:
    """
    --video_geotag_source '{"source": "native", "filetypes": ["blackvue"]}' and
    the default sources for images, as process_geotag_properties() makes them
    """
    return [
        SourceOption(SourceType.NATIVE, filetypes={types.FileType.BLACKVUE}),
        SourceOption(SourceType.NATIVE, filetypes={types.FileType.IMAGE}),
        SourceOption(SourceType.EXIFTOOL_RUNTIME, filetypes={types.FileType.IMAGE}),
    ]


class TestFilesNoSourceIsGiven:
    """
    The filetypes of every source, limited to --filetypes if given, can leave
    out a file, which --filetypes lets in. It was left out, as if it had not
    been there
    """

    def test_video_of_a_type_asked_for_is_reported(self):
        video = DATA / "gopro_data" / "max-360mode.mp4"
        [result] = _process_without_stubs(
            [video], _blackvue_source_and_default_image_sources(), GOPRO
        )
        assert isinstance(result, types.ErrorMetadata)
        assert isinstance(result.error, exceptions.MapillaryVideoGPSNotFoundError)
        assert result.filename == video
        assert str(result.error) == (
            "--filetypes gopro leaves no geotag source for this video: the geotag "
            "sources native, exiftool_runtime are limited to other file types"
        )

    def test_video_of_another_type_is_left_out(self):
        video = DATA / "videos" / "sample-5s.mp4"
        results = _process_without_stubs(
            [video], _blackvue_source_and_default_image_sources(), GOPRO
        )
        assert results == []

    def test_any_video_with_filetypes_video(self):
        video = DATA / "videos" / "sample-5s.mp4"
        [result] = _process_without_stubs(
            [video],
            [SourceOption(SourceType.EXIF, filetypes={types.FileType.IMAGE})],
            {types.FileType.VIDEO},
        )
        assert isinstance(result, types.ErrorMetadata)
        assert str(result.error).startswith(
            "--filetypes video leaves no geotag source for this video"
        )

    def test_image(self):
        image = DATA / "images" / "DSC00001.JPG"
        options = [SourceOption(SourceType.NATIVE, filetypes={types.FileType.VIDEO})]
        [result] = _process_without_stubs([image], options, {types.FileType.IMAGE})
        assert isinstance(result, types.ErrorMetadata)
        assert isinstance(result.error, exceptions.MapillaryGeoTaggingError)
        assert result.filetype is types.FileType.IMAGE

    @pytest.mark.parametrize(
        ("path", "source_filetype", "kind"),
        [
            (DATA / "images" / "DSC00001.JPG", types.FileType.VIDEO, "image"),
            (DATA / "videos" / "sample-5s.mp4", types.FileType.IMAGE, "video"),
        ],
    )
    def test_without_filetypes(self, path, source_filetype, kind):
        """
        Left out by the filetypes of the sources alone. Without --filetypes no
        type is left out, so a video is reported without reading its type
        """
        options = [SourceOption(SourceType.NATIVE, filetypes={source_filetype})]
        [result] = _process_without_stubs([path], options, None)
        assert isinstance(result, types.ErrorMetadata)
        assert str(result.error) == (
            f"No geotag source is given for this {kind}: the geotag source native "
            "is limited to other file types"
        )


def _process_without_stubs(
    paths: T.Sequence[Path],
    options: T.Sequence[SourceOption],
    filetypes: set[types.FileType] | None,
) -> list[types.MetadataOrError]:
    """factory.process() as process_geotag_properties() calls it, in this process"""
    for option in options:
        option.filetypes = types.combine_filetype_filters(option.filetypes, filetypes)
        option.num_processes = 0
    return factory.process(paths, options, filetypes)


class TestNativeVideoExtractor:
    """
    process() tells by the native reader's not found that a video is of none of
    the types the reader was given
    """

    def test_video_of_none_of_the_types(self):
        with pytest.raises(exceptions.MapillaryVideoGPSNotFoundError):
            NativeVideoExtractor(
                DATA / "videos" / "sample-5s.mp4", filetypes=GOPRO
            ).extract()

    def test_video_of_another_type(self):
        with pytest.raises(exceptions.MapillaryVideoGPSNotFoundError):
            NativeVideoExtractor(
                DATA / "gopro_data" / "max-360mode.mp4",
                filetypes={types.FileType.BLACKVUE, types.FileType.CAMM},
            ).extract()

    def test_video_of_the_type_without_usable_gps(self):
        """Recognized as a GoPro video, whose GPS is all noise"""
        with pytest.raises(exceptions.MapillaryGPSNoiseError):
            NativeVideoExtractor(
                DATA / "gopro_data" / "hero8.mp4", filetypes=GOPRO
            ).extract()
