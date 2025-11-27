from __future__ import annotations

import itertools
import typing as T
from pathlib import Path

import py.path
import pytest
from mapillary_tools import (
    exceptions,
    geo,
    process_geotag_properties as pgp,
    process_sequence_properties as psp,
    types,
)
from mapillary_tools.serializer import description


def _make_image_metadata(
    filename: Path,
    lng: float,
    lat: float,
    time: float,
    angle: float | None = None,
    filesize: int = 0,
    **kwargs,
) -> types.ImageMetadata:
    return types.ImageMetadata(
        filename=filename.resolve(),
        filesize=filesize,
        lon=lng,
        lat=lat,
        time=time,
        alt=None,
        angle=angle,
        **kwargs,
    )


def test_find_sequences_by_folder(tmpdir: py.path.local):
    curdir = tmpdir.mkdir("hello1").mkdir("world2")
    sequence: T.List[types.MetadataOrError] = [
        types.ErrorMetadata(
            filename=Path("error.jpg"),
            filetype=types.FileType.IMAGE,
            error=Exception("an error"),
        ),
        # s1
        _make_image_metadata(
            Path(curdir) / Path("hello/foo.jpg"), 1.00001, 1.00001, 2, 11
        ),
        _make_image_metadata(
            Path(curdir) / Path("./hello/bar.jpg"),
            1.00002,
            1.00002,
            8,
            22,
        ),
        _make_image_metadata(
            Path(curdir) / Path("hello/a.jpg"), 1.00002, 1.00002, 9, 33
        ),
        # s2
        _make_image_metadata(Path(curdir) / Path("hello.jpg"), 1.00002, 1.00002, 2, 11),
        _make_image_metadata(Path(curdir) / Path("./foo.jpg"), 1.00001, 1.00001, 3, 22),
        _make_image_metadata(Path(curdir) / Path("a.jpg"), 1.00001, 1.00001, 1, 33),
        # s3
        _make_image_metadata(
            Path(curdir) / Path("./../foo.jpg"), 1.00001, 1.00001, 19, 11
        ),
        _make_image_metadata(
            Path(curdir) / Path("../bar.jpg"), 1.00002, 1.00002, 28, 22
        ),
    ]
    metadatas = psp.process_sequence_properties(
        sequence,
        cutoff_distance=1000000,
        cutoff_time=10000,
        interpolate_directions=False,
        duplicate_distance=0,
        duplicate_angle=0,
    )
    assert len(metadatas) == len(sequence)
    image_metadatas = [d for d in metadatas if isinstance(d, types.ImageMetadata)]

    actual_metadata: T.Dict[str, T.List[types.ImageMetadata]] = {}
    for d in image_metadatas:
        actual_metadata.setdefault(d.MAPSequenceUUID or "", []).append(d)

    for s in actual_metadata.values():
        for c, n in geo.pairwise(s):
            assert c.time <= n.time

    actual_sequences = sorted(
        list(actual_metadata.values()), key=lambda s: str(s[0].filename)
    )
    assert 3 == len(actual_sequences)

    assert [
        (Path(curdir) / Path("../foo.jpg")).resolve(),
        (Path(curdir) / Path("../bar.jpg")).resolve(),
    ] == [d.filename for d in actual_sequences[0]]
    assert [
        Path(curdir) / Path("a.jpg"),
        Path(curdir) / Path("hello.jpg"),
        Path(curdir) / Path("foo.jpg"),
    ] == [d.filename for d in actual_sequences[1]]
    assert [
        Path(curdir) / Path("hello/foo.jpg"),
        Path(curdir) / Path("hello/bar.jpg"),
        Path(curdir) / Path("hello/a.jpg"),
    ] == [d.filename for d in actual_sequences[2]]


def test_find_sequences_by_camera(tmpdir: py.path.local):
    curdir = tmpdir.mkdir("hello1").mkdir("world2")
    sequence: T.List[types.MetadataOrError] = [
        # s1
        _make_image_metadata(
            Path(curdir) / Path("hello.jpg"),
            1.00002,
            1.00002,
            2,
            11,
            MAPDeviceMake="foo",
            MAPDeviceModel="bar",
            width=1,
            height=1,
        ),
        _make_image_metadata(
            Path(curdir) / Path("foo.jpg"),
            1.00001,
            1.00001,
            3,
            22,
            MAPDeviceMake="foo",
            MAPDeviceModel="bar",
            width=1,
            height=1,
        ),
        # s2
        _make_image_metadata(
            Path(curdir) / Path("a.jpg"),
            1.00002,
            1.00002,
            1,
            33,
            MAPDeviceMake="foo",
            MAPDeviceModel="bar2",
            width=1,
            height=1,
        ),
        # s3
        _make_image_metadata(
            Path(curdir) / Path("b.jpg"),
            1.00001,
            1.00001,
            1,
            33,
            MAPDeviceMake="foo",
            MAPDeviceModel="bar2",
            width=1,
            height=2,
        ),
    ]
    metadatas = psp.process_sequence_properties(
        sequence,
    )
    uuids = set(
        d.MAPSequenceUUID for d in metadatas if isinstance(d, types.ImageMetadata)
    )
    assert len(uuids) == 3


def test_sequences_sorted(tmpdir: py.path.local):
    curdir = tmpdir.mkdir("hello1").mkdir("world2")
    sequence: T.List[types.ImageMetadata] = [
        # s1
        _make_image_metadata(Path(curdir) / Path("./c.jpg"), 1, 1, 1),
        _make_image_metadata(Path(curdir) / Path("a.jpg"), 1.00001, 1.00001, 2),
        _make_image_metadata(Path(curdir) / Path("b.jpg"), 1.00002, 1.00002, 2),
        _make_image_metadata(Path(curdir) / Path("c.jpg"), 1.00002, 1.00002, 2.1),
        _make_image_metadata(Path(curdir) / Path("d.jpg"), 1.00002, 1.00002, 2.1),
        _make_image_metadata(Path(curdir) / Path("e.jpg"), 1.00002, 1.00002, 2.2),
        _make_image_metadata(Path(curdir) / Path("f.jpg"), 1.00002, 1.00002, 2.25003),
        _make_image_metadata(Path(curdir) / Path("g.jpg"), 1.00002, 1.00002, 2.25009),
        _make_image_metadata(Path(curdir) / Path("x.jpg"), 1.00002, 1.00002, 2.26),
        _make_image_metadata(Path(curdir) / Path("y.jpg"), 1.00002, 1.00002, 4),
        _make_image_metadata(Path(curdir) / Path("z.jpg"), 1.00002, 1.00002, 4.399),
        _make_image_metadata(Path(curdir) / Path("ha.jpg"), 1.00002, 1.00002, 4.399999),
        _make_image_metadata(Path(curdir) / Path("ha.jpg"), 1.00002, 1.00002, 4.399999),
        _make_image_metadata(Path(curdir) / Path("ha.jpg"), 1.00002, 1.00002, 4.4),
    ]
    metadatas = psp.process_sequence_properties(
        sequence,
        cutoff_distance=100,
        cutoff_time=10,
        interpolate_directions=False,
        duplicate_distance=0,
        duplicate_angle=0,
    )
    image_metadatas = [d for d in metadatas if isinstance(d, types.ImageMetadata)]
    expected = [
        1,
        2.0,
        2.05,
        2.1,
        2.15,
        2.2,
        2.25003,
        2.255015,
        2.26,
        4,
        4.399,
        4.399333333333334,
        4.399666666666667,
        4.4,
    ]
    for x, y in zip(expected, [x.time for x in image_metadatas]):
        assert abs(x - y) < 0.00001, (x, y)


def test_cut_sequences(tmpdir: py.path.local):
    curdir = tmpdir.mkdir("hello11").mkdir("world22")
    sequence: T.List[types.ImageMetadata] = [
        # s1
        _make_image_metadata(Path(curdir) / Path("./c.jpg"), 1, 1, 1),
        _make_image_metadata(Path(curdir) / Path("a.jpg"), 1.00001, 1.00001, 2),
        _make_image_metadata(Path(curdir) / Path("b.jpg"), 1.00002, 1.00002, 2),
        # s2
        _make_image_metadata(Path(curdir) / Path("foo/b.jpg"), 1.00090, 1.00090, 2),
        _make_image_metadata(Path(curdir) / Path("foo/a.jpg"), 1.00091, 1.00091, 3),
        # s3
        _make_image_metadata(Path(curdir) / Path("../a.jpg"), 1.00092, 1.00092, 19),
        _make_image_metadata(Path(curdir) / Path("../b.jpg"), 1.00093, 1.00093, 28),
    ]
    metadatas = psp.process_sequence_properties(
        sequence,
        cutoff_distance=100,
        cutoff_time=10,
        interpolate_directions=False,
        duplicate_distance=0,
        duplicate_angle=0,
    )
    image_metadatas = [d for d in metadatas if isinstance(d, types.ImageMetadata)]
    actual_seqs = []
    for key, seq in itertools.groupby(image_metadatas, key=lambda d: d.MAPSequenceUUID):
        actual_seqs.append(list(seq))
    assert len(actual_seqs) == 3
    actual_seqs.sort(key=lambda d: d[0].time)
    assert [img.filename for img in sequence[0:3]] == [
        img.filename for img in actual_seqs[0]
    ]
    assert [img.filename for img in sequence[3:5]] == [
        img.filename for img in actual_seqs[1]
    ]
    assert [img.filename for img in sequence[5:7]] == [
        img.filename for img in actual_seqs[2]
    ]


def test_duplication(tmpdir: py.path.local):
    curdir = tmpdir.mkdir("hello111").mkdir("world222")
    sequence = [
        # s1
        _make_image_metadata(Path(curdir) / Path("./a.jpg"), 1, 1, 1, angle=0),
        _make_image_metadata(
            Path(curdir) / Path("./b.jpg"), 1.00001, 1.00001, 2, angle=1
        ),
        _make_image_metadata(
            Path(curdir) / Path("./c.jpg"), 1.00002, 1.00002, 3, angle=-1
        ),
        _make_image_metadata(
            Path(curdir) / Path("./d.jpg"), 1.00003, 1.00003, 4, angle=-2
        ),
        _make_image_metadata(
            Path(curdir) / Path("./e.jpg"), 1.00009, 1.00009, 5, angle=5
        ),
        _make_image_metadata(
            Path(curdir) / Path("./f.jpg"), 1.00090, 1.00090, 6, angle=5
        ),
        _make_image_metadata(
            Path(curdir) / Path("./d.jpg"), 1.00091, 1.00091, 7, angle=-1
        ),
    ]
    metadatas = psp.process_sequence_properties(
        sequence,
        cutoff_distance=100000,
        cutoff_time=100,
        interpolate_directions=False,
        duplicate_distance=100,
        duplicate_angle=5,
    )
    assert len(metadatas) == len(sequence)
    error_metadatas = [d for d in metadatas if isinstance(d, types.ErrorMetadata)]
    assert len(error_metadatas) == 4
    assert set(d.filename for d in sequence[1:-2]) == set(
        Path(d.error.desc["filename"])
        for d in error_metadatas  # type: ignore
    )


def test_interpolation(tmpdir: py.path.local):
    curdir = tmpdir.mkdir("hello222").mkdir("world333")
    sequence: T.List[types.Metadata] = [
        # s1
        _make_image_metadata(
            Path(curdir) / Path("./a.jpg"), 0.00002, 0.00001, 3, angle=344
        ),
        _make_image_metadata(
            Path(curdir) / Path("./b.jpg"), 0.00001, 0.00001, 4, angle=22
        ),
        _make_image_metadata(
            Path(curdir) / Path("./c.jpg"), 0.00001, 0.00000, 5, angle=-123
        ),
        _make_image_metadata(
            Path(curdir) / Path("./d.jpg"), 0.00001, 0.00000, 1, angle=2
        ),
        _make_image_metadata(
            Path(curdir) / Path("./e.jpg"), 0.00002, 0.00000, 2, angle=123
        ),
        types.VideoMetadata(
            Path("test_video.mp4"),
            types.FileType.IMAGE,
            points=[],
            make="hello",
            model="world",
            filesize=123,
        ),
    ]
    metadatas = psp.process_sequence_properties(
        sequence,
        cutoff_distance=1000000000,
        cutoff_time=100,
        interpolate_directions=True,
        duplicate_distance=100,
        duplicate_angle=5,
    )
    assert 6 == len(metadatas)
    image_metadatas = [d for d in metadatas if isinstance(d, types.ImageMetadata)]
    image_metadatas.sort(key=lambda d: d.time)
    assert [90, 0, 270, 180, 180] == [
        int(metadata.angle)
        for metadata in image_metadatas
        if metadata.angle is not None
    ]


def test_subsec_interpolation(tmpdir: py.path.local):
    curdir = tmpdir.mkdir("hello222").mkdir("world333")
    sequence: T.List[types.Metadata] = [
        # s1
        _make_image_metadata(Path(curdir) / Path("./a.jpg"), 0.00001, 0.00001, 0.0, 1),
        _make_image_metadata(Path(curdir) / Path("./b.jpg"), 0.00000, 0.00001, 1.0, 11),
        _make_image_metadata(Path(curdir) / Path("./c.jpg"), 0.00001, 0.00001, 1.0, 22),
        _make_image_metadata(Path(curdir) / Path("./d.jpg"), 0.00001, 0.00001, 1.0, 33),
        _make_image_metadata(Path(curdir) / Path("./e.jpg"), 0.00001, 0.00000, 2.0, 44),
    ]
    metadatas = psp.process_sequence_properties(
        sequence,
        cutoff_distance=1000000000,
        cutoff_time=100,
        interpolate_directions=True,
        duplicate_distance=100,
        duplicate_angle=5,
    )

    assert 5 == len(metadatas)
    image_metadatas = [d for d in metadatas if isinstance(d, types.ImageMetadata)]
    image_metadatas.sort(key=lambda d: d.time)

    assert [0, 1, 1.3, 1.6, 2] == [
        int(metadata.time * 10) / 10 for metadata in image_metadatas
    ]


def test_interpolation_single(tmpdir: py.path.local):
    curdir = tmpdir.mkdir("hello77").mkdir("world88")
    sequence = [
        # s1
        _make_image_metadata(Path(curdir) / Path("./a.jpg"), 0.2, 0.3, 1, angle=123),
    ]
    metadatas = psp.process_sequence_properties(
        sequence,
        cutoff_distance=1000000000,
        cutoff_time=100,
        interpolate_directions=True,
        duplicate_distance=100,
        duplicate_angle=5,
    )
    image_metadatas = [d for d in metadatas if isinstance(d, types.ImageMetadata)]
    assert [0] == [
        int(metadata.angle)
        for metadata in image_metadatas
        if metadata.angle is not None
    ]


IMPORT_PATH = "tests/unit/data"


@pytest.fixture
def setup_data(tmpdir: py.path.local):
    data_path = tmpdir.mkdir("data")
    source = py.path.local(IMPORT_PATH)
    source.copy(data_path)
    yield data_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


def test_process_finalize(setup_data):
    test_exif = setup_data.join("test_exif.jpg")
    corrupt_exif = setup_data.join("corrupt_exif.jpg")
    # toobig = _make_image_metadata(Path(corrupt_exif), 1, 1, 4, angle=22)
    # toobig.MAPDeviceModel = "iPhone 11" * 100000
    sequence: T.List[types.MetadataOrError] = [
        _make_image_metadata(Path(test_exif), 1, 1, 3, angle=344),
        _make_image_metadata(Path(corrupt_exif), 1000, 1, 4, angle=22),
        types.VideoMetadata(
            Path(setup_data.join("test_video.mp4")),
            types.FileType.IMAGE,
            points=[],
            make="hello",
            model="world",
        ),
        # toobig,
    ]
    pytest.raises(
        exceptions.MapillaryProcessError, lambda: pgp.process_finalize([], sequence)
    )
    # pgp.process_finalize([], sequence, skip_process_errors=True)
    actual = pgp.process_finalize(
        [],
        sequence,
        overwrite_all_EXIF_tags=True,
        overwrite_EXIF_time_tag=True,
        overwrite_EXIF_gps_tag=True,
        overwrite_EXIF_direction_tag=True,
        overwrite_EXIF_orientation_tag=True,
        offset_time=-1.0,
        offset_angle=33.0,
        skip_process_errors=True,
    )
    expected = [
        {
            "filename": str(test_exif),
            "filetype": "image",
            "filesize": 0,
            "MAPFilename": "test_exif.jpg",
            "MAPLatitude": 1,
            "MAPLongitude": 1,
            "MAPCaptureTime": "1970_01_01_00_00_02_000",
            "MAPCompassHeading": {"TrueHeading": 17.0, "MagneticHeading": 17.0},
            "md5sum": None,
        },
        {
            "error": {
                "type": "MapillaryMetadataValidationError",
                "message": "1000 is greater than the maximum of 180",
            },
            "filename": str(corrupt_exif),
            "filetype": "image",
        },
        {
            "error": {
                "type": "MapillaryMetadataValidationError",
                "message": "'image' is not one of ['camm', 'gopro', 'blackvue', 'video']",
            },
            "filename": str(setup_data.join("test_video.mp4")),
            "filetype": "image",
        },
        # {
        #     "error": {
        #         "type": "error",
        #         "message": "'H' format requires 0 <= number <= 65535",
        #     },
        #     "filename": str(corrupt_exif),
        #     "filetype": "image",
        # },
    ]
    assert expected == [
        description.DescriptionJSONSerializer.as_desc(d) for d in actual
    ]


def test_cut_by_pixels(tmpdir: py.path.local):
    sequence: T.List[types.Metadata] = [
        # s2
        _make_image_metadata(
            Path(tmpdir) / Path("./a.jpg"),
            2,
            2,
            1,
            angle=344,
            width=2,
            height=2,
        ),
        _make_image_metadata(
            Path(tmpdir) / Path("./b.jpg"),
            2.00001,
            2.00001,
            20,
            angle=344,
            width=2,
            height=2,
        ),
        # s1
        _make_image_metadata(
            Path(tmpdir) / Path("./c.jpg"),
            2.00002,
            2.00002,
            30,
            angle=344,
            width=int(6e9),
            height=2,
        ),
    ]
    metadatas = psp.process_sequence_properties(
        sequence,
        cutoff_distance=1000000000,
        cutoff_time=100,
        interpolate_directions=True,
        duplicate_distance=1,
        duplicate_angle=5,
    )
    assert (
        len(
            set(
                m.MAPSequenceUUID
                for m in metadatas
                if isinstance(m, types.ImageMetadata)
            )
        )
        == 2
    )


def test_video_error(tmpdir: py.path.local):
    sequence: T.List[types.Metadata] = [
        types.VideoMetadata(
            Path(tmpdir) / Path("test_video_null_island.mp4"),
            types.FileType.VIDEO,
            points=[
                geo.Point(1, -0.00001, -0.00001, 1, angle=None),
                geo.Point(1, 0, 0, 1, angle=None),
                geo.Point(1, 0.00010, 0.00010, 1, angle=None),
            ],
            make="hello",
            model="world",
            filesize=123,
        ),
        types.VideoMetadata(
            Path(tmpdir) / Path("test_video_too_fast.mp4"),
            types.FileType.VIDEO,
            points=[
                geo.Point(1, 1, 1, 1, angle=None),
                geo.Point(1.1, 1.00001, 1.00001, 1, angle=None),
                geo.Point(10, 1, 3, 1, angle=None),
            ],
            make="hello",
            model="world",
            filesize=123,
        ),
        types.VideoMetadata(
            Path(tmpdir) / Path("test_video_file_too_large.mp4"),
            types.FileType.VIDEO,
            points=[
                geo.Point(1, 1, 1, 1, angle=None),
                geo.Point(2, 1.0002, 1.0002, 1, angle=None),
            ],
            make="hello",
            model="world",
            filesize=1024 * 1024 * 1024 * 200,
        ),
        types.VideoMetadata(
            Path(tmpdir) / Path("test_good.mp4"),
            types.FileType.VIDEO,
            points=[
                geo.Point(1, 1, 1, 1, angle=None),
                geo.Point(2, 1.0002, 1.0002, 1, angle=None),
            ],
            make="hello",
            model="world",
            filesize=123,
        ),
    ]
    metadatas = psp.process_sequence_properties(
        sequence,
        cutoff_distance=1000000000,
        cutoff_time=100,
        interpolate_directions=True,
        duplicate_distance=100,
        duplicate_angle=5,
    )
    metadata_by_filename = {m.filename.name: m for m in metadatas}
    assert isinstance(metadata_by_filename["test_good.mp4"], types.VideoMetadata)
    assert isinstance(
        metadata_by_filename["test_video_null_island.mp4"], types.ErrorMetadata
    ) and isinstance(
        metadata_by_filename["test_video_null_island.mp4"].error,
        exceptions.MapillaryNullIslandError,
    )
    assert isinstance(
        metadata_by_filename["test_video_file_too_large.mp4"], types.ErrorMetadata
    ) and isinstance(
        metadata_by_filename["test_video_file_too_large.mp4"].error,
        exceptions.MapillaryFileTooLargeError,
    )
    assert isinstance(
        metadata_by_filename["test_video_too_fast.mp4"], types.ErrorMetadata
    ) and isinstance(
        metadata_by_filename["test_video_too_fast.mp4"].error,
        exceptions.MapillaryCaptureSpeedTooFastError,
    )


def test_split_sequence_by_filesize(tmpdir):
    sequence: T.List[types.Metadata] = [
        # s1
        _make_image_metadata(
            Path(tmpdir) / Path("./a.jpg"), 2, 2, 1, filesize=110 * 1024 * 1024 * 1024
        ),
        # s2
        _make_image_metadata(
            Path(tmpdir) / Path("./b.jpg"), 2.00001, 2.00001, 2, filesize=1
        ),
        _make_image_metadata(
            Path(tmpdir) / Path("./c.jpg"), 2.00002, 2.00002, 2, filesize=1
        ),
    ]

    metadatas = psp.process_sequence_properties(sequence)
    assert 2 == len({m.MAPSequenceUUID for m in metadatas})  # type: ignore


def test_split_sequence_by_image_count(tmpdir):
    max_allowed_images = 1000

    sequence = []
    for i in range(1, max_allowed_images + 1):
        image = _make_image_metadata(
            Path(tmpdir) / Path(f"./a{i}.jpg"),
            1 + i * 0.00001,
            1 + i * 0.00001,
            i,
            filesize=1,
        )
        sequence.append(image)

    metadatas = psp.process_sequence_properties(sequence)
    assert 1 == len({m.MAPSequenceUUID for m in metadatas}), metadatas  # type: ignore


def test_split_sequence_by_image_count_split(tmpdir):
    max_allowed_images = 1000

    sequence = []
    for i in range(1, max_allowed_images + 2):
        image = _make_image_metadata(
            Path(tmpdir) / Path(f"./a{i}.jpg"),
            1 + i * 0.00001,
            1 + i * 0.00001,
            i,
            filesize=1,
        )
        sequence.append(image)

    metadatas = psp.process_sequence_properties(sequence)
    assert 2 == len({m.MAPSequenceUUID for m in metadatas}), metadatas  # type: ignore


def test_split_sequence_by_cutoff_time(tmpdir):
    sequence: T.List[types.Metadata] = [
        # s1
        _make_image_metadata(Path(tmpdir) / Path("./a.jpg"), 1, 1, 1, filesize=1),
        # s2
        _make_image_metadata(
            Path(tmpdir) / Path("./b.jpg"), 1.00001, 1.00001, 600, filesize=1
        ),
        _make_image_metadata(
            Path(tmpdir) / Path("./c.jpg"), 1.00002, 1.00002, 601, filesize=1
        ),
    ]

    metadatas = psp.process_sequence_properties(sequence)
    assert 2 == len({m.MAPSequenceUUID for m in metadatas}), metadatas  # type: ignore


def test_split_sequence_no_split(tmpdir):
    sequence: T.List[types.Metadata] = [
        # s1
        _make_image_metadata(Path(tmpdir) / Path("./a.jpg"), 1, 1, 1),
        # s2
        _make_image_metadata(Path(tmpdir) / Path("./b.jpg"), 1.00001, 1.00001, 2),
        # s3
        _make_image_metadata(Path(tmpdir) / Path("./c.jpg"), 1.00002, 1.00002, 3),
    ]

    metadatas = psp.process_sequence_properties(sequence)
    assert 1 == len({m.MAPSequenceUUID for m in metadatas}), metadatas  # type: ignore
