import dataclasses
import io
import typing as T
from pathlib import Path

from mapillary_tools import geo, telemetry, types, upload
from mapillary_tools.camm import camm_builder, camm_parser
from mapillary_tools.mp4 import construct_mp4_parser as cparser, simple_mp4_builder


def test_filter_points_by_edit_list():
    assert [] == list(camm_parser._filter_telemetry_by_elst_segments([], []))
    points = [
        geo.Point(time=0, lat=0, lon=0, alt=None, angle=None),
        geo.Point(time=0.23, lat=0, lon=0, alt=None, angle=None),
        geo.Point(time=0.29, lat=0, lon=0, alt=None, angle=None),
        geo.Point(time=0.31, lat=0, lon=0, alt=None, angle=None),
    ]
    assert points == list(camm_parser._filter_telemetry_by_elst_segments(points, []))
    assert [dataclasses.replace(p, time=p.time + 4.4) for p in points] == list(
        camm_parser._filter_telemetry_by_elst_segments(points, [(-1, 3), (-1, 4.4)])
    )

    assert [
        geo.Point(time=0.23 + 4.4, lat=0, lon=0, alt=None, angle=None),
        geo.Point(time=0.31 + 4.4, lat=0, lon=0, alt=None, angle=None),
    ] == list(
        camm_parser._filter_telemetry_by_elst_segments(
            points, [(-1, 3), (-1, 4.4), (0.21, 0.04), (0.30, 0.04)]
        )
    )

    assert [
        geo.Point(time=0.29 + 4.4, lat=0, lon=0, alt=None, angle=None),
        geo.Point(time=0.31 + 4.4, lat=0, lon=0, alt=None, angle=None),
    ] == list(
        camm_parser._filter_telemetry_by_elst_segments(points, [(-1, 4.4), (0.24, 0.3)])
    )


# TODO: use CAMMInfo as input
def encode_decode_empty_camm_mp4(metadata: types.VideoMetadata) -> types.VideoMetadata:
    movie_timescale = 1_000_000

    mvhd: cparser.BoxDict = {
        "type": b"mvhd",
        "data": {
            "creation_time": 1,
            "modification_time": 2,
            "timescale": movie_timescale,
            "duration": int(36000 * movie_timescale),
        },
    }

    empty_mp4: T.List[cparser.BoxDict] = [
        {"type": b"ftyp", "data": b"test"},
        {"type": b"moov", "data": [mvhd]},
    ]
    src = cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist(empty_mp4)
    input_camm_info = upload._prepare_camm_info(metadata)
    target_fp = simple_mp4_builder.transform_mp4(
        io.BytesIO(src), camm_builder.camm_sample_generator2(input_camm_info)
    )

    # extract points
    camm_info = camm_parser.extract_camm_info(T.cast(T.BinaryIO, target_fp))

    assert camm_info is not None

    # return metadata
    return types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=T.cast(T.List[geo.Point], camm_info.gps or camm_info.mini_gps),
        make=camm_info.make,
        model=camm_info.model,
    )


def approximate(expected, actual):
    assert len(expected) == len(actual)

    for x, y in zip(expected, actual):
        x = dataclasses.asdict(x)
        y = dataclasses.asdict(y)

        keys = set([*x.keys(), *y.keys()])
        for k in keys:
            if isinstance(x[k], float):
                assert abs(x[k] - y[k]) < 10e-6
            else:
                assert x[k] == y[k]


def test_build_and_parse_points():
    points = [
        geo.Point(time=-0.1, lat=0.01, lon=0.2, alt=None, angle=None),
        geo.Point(time=0.1, lat=0.01, lon=0.2, alt=None, angle=None),
        geo.Point(time=0.23, lat=0.001, lon=0.21, alt=None, angle=None),
        geo.Point(time=0.29, lat=0.002, lon=0.203, alt=None, angle=None),
        geo.Point(time=0.31, lat=0.0025, lon=0.2004, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
    )
    x = encode_decode_empty_camm_mp4(metadata)
    approximate(
        [
            geo.Point(time=0.1, lat=0.01, lon=0.2, alt=-1.0, angle=None),
            geo.Point(time=0.23, lat=0.001, lon=0.21, alt=-1.0, angle=None),
            geo.Point(time=0.29, lat=0.002, lon=0.203, alt=-1.0, angle=None),
            geo.Point(time=0.31, lat=0.0025, lon=0.2004, alt=-1.0, angle=None),
        ],
        x.points,
    )


def test_build_and_parse_camm_gps_points():
    points = [
        telemetry.CAMMGPSPoint(
            time=-0.1,
            lat=0.01,
            lon=0.2,
            alt=None,
            angle=None,
            time_gps_epoch=1.1,
            gps_fix_type=1,
            horizontal_accuracy=3.3,
            vertical_accuracy=4.4,
            velocity_east=5.5,
            velocity_north=6.6,
            velocity_up=7.7,
            speed_accuracy=8.0,
        ),
        telemetry.CAMMGPSPoint(
            time=0.1,
            lat=0.01,
            lon=0.2,
            alt=None,
            angle=None,
            time_gps_epoch=1.2,
            gps_fix_type=1,
            horizontal_accuracy=3.3,
            vertical_accuracy=4.4,
            velocity_east=5.5,
            velocity_north=6.6,
            velocity_up=7.7,
            speed_accuracy=8.0,
        ),
        telemetry.CAMMGPSPoint(
            time=0.23,
            lat=0.001,
            lon=0.21,
            alt=None,
            angle=None,
            time_gps_epoch=1.3,
            gps_fix_type=1,
            horizontal_accuracy=3.3,
            vertical_accuracy=4.4,
            velocity_east=5.5,
            velocity_north=6.6,
            velocity_up=7.7,
            speed_accuracy=8.0,
        ),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
    )
    x = encode_decode_empty_camm_mp4(metadata)
    approximate(
        [
            telemetry.CAMMGPSPoint(
                time=0.1,
                lat=0.01,
                lon=0.2,
                alt=-1,
                angle=None,
                time_gps_epoch=1.2,
                gps_fix_type=1,
                horizontal_accuracy=3.3,
                vertical_accuracy=4.4,
                velocity_east=5.5,
                velocity_north=6.6,
                velocity_up=7.7,
                speed_accuracy=8.0,
            ),
            telemetry.CAMMGPSPoint(
                time=0.23,
                lat=0.001,
                lon=0.21,
                alt=-1,
                angle=None,
                time_gps_epoch=1.3,
                gps_fix_type=1,
                horizontal_accuracy=3.3,
                vertical_accuracy=4.4,
                velocity_east=5.5,
                velocity_north=6.6,
                velocity_up=7.7,
                speed_accuracy=8.0,
            ),
        ],
        x.points,
    )


def test_build_and_parse_single_points():
    points = [
        geo.Point(time=1.2, lat=0.01, lon=0.2, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
    )
    x = encode_decode_empty_camm_mp4(metadata)
    approximate(
        [
            geo.Point(time=1.2, lat=0.01, lon=0.2, alt=-1.0, angle=None),
        ],
        x.points,
    )


def test_build_and_parse_single_point_0():
    points = [
        geo.Point(time=0, lat=0.01, lon=0.2, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
    )
    x = encode_decode_empty_camm_mp4(metadata)
    approximate(
        [
            geo.Point(time=0, lat=0.01, lon=0.2, alt=-1.0, angle=None),
        ],
        x.points,
    )


def test_build_and_parse_single_point_neg():
    points = [
        geo.Point(time=-1.2, lat=0.01, lon=0.2, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
    )
    x = encode_decode_empty_camm_mp4(metadata)
    approximate([], x.points)


def test_build_and_parse_start_early():
    points = [
        geo.Point(time=-1, lat=0.01, lon=0.2, alt=None, angle=None),
        geo.Point(time=1.2, lat=0.01, lon=0.2, alt=None, angle=None),
        geo.Point(time=1.4, lat=0.01, lon=0.2, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
    )
    x = encode_decode_empty_camm_mp4(metadata)
    approximate(
        [
            geo.Point(time=1.2, lat=0.01, lon=0.2, alt=-1, angle=None),
            geo.Point(time=1.4, lat=0.01, lon=0.2, alt=-1, angle=None),
        ],
        x.points,
    )


def test_build_and_parse2():
    points = [
        geo.Point(time=0.1, lat=0.01, lon=0.2, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
        make="test_make汉字",
        model="test_model汉字",
    )
    x = encode_decode_empty_camm_mp4(metadata)
    assert x.make == "test_make汉字"
    assert x.model == "test_model汉字"
    approximate(
        [geo.Point(time=0.09999999988358468, lat=0.01, lon=0.2, alt=-1.0, angle=None)],
        x.points,
    )


def test_build_and_parse9():
    points = [
        geo.Point(time=0.0, lat=0.01, lon=0.2, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
        make="test_make汉字",
        model="test_model汉字",
    )
    x = encode_decode_empty_camm_mp4(metadata)
    assert [geo.Point(time=0.0, lat=0.01, lon=0.2, alt=-1.0, angle=None)] == x.points


def test_build_and_parse10():
    points = [
        geo.Point(time=0.0, lat=0.01, lon=0.2, alt=None, angle=None),
        geo.Point(time=0.1, lat=0.03, lon=0.2, alt=None, angle=None),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
        make="test_make汉字",
        model="test_model汉字",
    )
    x = encode_decode_empty_camm_mp4(metadata)
    approximate(
        [
            geo.Point(time=0.0, lat=0.01, lon=0.2, alt=-1.0, angle=None),
            geo.Point(time=0.1, lat=0.03, lon=0.2, alt=-1.0, angle=None),
        ],
        x.points,
    )


def test_build_and_parse3():
    points = []
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
        make="test_make汉字",
        model="test_model汉字",
    )
    x = encode_decode_empty_camm_mp4(metadata)
    assert [] == x.points
