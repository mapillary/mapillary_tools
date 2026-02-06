# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import dataclasses
import io
import typing as T
from pathlib import Path

from mapillary_tools import geo, telemetry, types, uploader
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
    input_camm_info = uploader.VideoUploader.prepare_camm_info(metadata)
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


def test_build_and_parse_gpx_sourced_camm_gps_points():
    """Test CAMMGPSPoint objects as created from GPX data (zeroed accuracy/velocity)."""
    points = [
        telemetry.CAMMGPSPoint(
            time=0.0,
            lat=37.7749,
            lon=-122.4194,
            alt=10.0,
            angle=None,
            time_gps_epoch=1706000000.0,
            gps_fix_type=3,
            horizontal_accuracy=0.0,
            vertical_accuracy=0.0,
            velocity_east=0.0,
            velocity_north=0.0,
            velocity_up=0.0,
            speed_accuracy=0.0,
        ),
        telemetry.CAMMGPSPoint(
            time=1.0,
            lat=37.7750,
            lon=-122.4195,
            alt=11.0,
            angle=None,
            time_gps_epoch=1706000001.0,
            gps_fix_type=3,
            horizontal_accuracy=0.0,
            vertical_accuracy=0.0,
            velocity_east=0.0,
            velocity_north=0.0,
            velocity_up=0.0,
            speed_accuracy=0.0,
        ),
        telemetry.CAMMGPSPoint(
            time=2.0,
            lat=37.7751,
            lon=-122.4196,
            alt=12.0,
            angle=None,
            time_gps_epoch=1706000002.0,
            gps_fix_type=3,
            horizontal_accuracy=0.0,
            vertical_accuracy=0.0,
            velocity_east=0.0,
            velocity_north=0.0,
            velocity_up=0.0,
            speed_accuracy=0.0,
        ),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
    )
    x = encode_decode_empty_camm_mp4(metadata)
    # Verify points round-trip with time_gps_epoch preserved
    assert len(x.points) == 3
    for original, decoded in zip(points, x.points):
        assert isinstance(decoded, telemetry.CAMMGPSPoint)
        decoded_camm = T.cast(telemetry.CAMMGPSPoint, decoded)
        assert abs(original.time_gps_epoch - decoded_camm.time_gps_epoch) < 10e-6
        assert abs(original.lat - decoded_camm.lat) < 10e-6
        assert abs(original.lon - decoded_camm.lon) < 10e-6


def test_prepare_camm_info_gpspoint_with_epoch_time():
    """GPSPoint with valid epoch_time should be converted to CAMMGPSPoint and routed to camm_info.gps."""
    points = [
        telemetry.GPSPoint(
            time=0.0,
            lat=37.7749,
            lon=-122.4194,
            alt=10.0,
            angle=None,
            epoch_time=1706000000.0,
            fix=telemetry.GPSFix.FIX_3D,
            precision=1.5,
            ground_speed=5.0,
        ),
        telemetry.GPSPoint(
            time=1.0,
            lat=37.7750,
            lon=-122.4195,
            alt=11.0,
            angle=None,
            epoch_time=1706000001.0,
            fix=telemetry.GPSFix.FIX_2D,
            precision=2.0,
            ground_speed=6.0,
        ),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.GOPRO,
        points=points,
    )
    camm_info = uploader.VideoUploader.prepare_camm_info(metadata)

    # Should be routed to gps (type 6), not mini_gps (type 5)
    assert camm_info.gps is not None
    assert len(camm_info.gps) == 2
    assert camm_info.mini_gps is None

    # Verify conversion preserved fields
    for original, converted in zip(points, camm_info.gps):
        assert isinstance(converted, telemetry.CAMMGPSPoint)
        assert converted.lat == original.lat
        assert converted.lon == original.lon
        assert converted.alt == original.alt
        assert converted.time == original.time
        assert converted.time_gps_epoch == original.epoch_time

    # Verify fix type was correctly converted from GPSFix enum
    assert camm_info.gps[0].gps_fix_type == 3  # FIX_3D.value
    assert camm_info.gps[1].gps_fix_type == 2  # FIX_2D.value


def test_prepare_camm_info_gpspoint_without_epoch_time():
    """GPSPoint without epoch_time should remain in mini_gps (type 5)."""
    points = [
        telemetry.GPSPoint(
            time=0.0,
            lat=37.7749,
            lon=-122.4194,
            alt=10.0,
            angle=None,
            epoch_time=None,
            fix=telemetry.GPSFix.FIX_3D,
            precision=1.5,
            ground_speed=5.0,
        ),
        telemetry.GPSPoint(
            time=1.0,
            lat=37.7750,
            lon=-122.4195,
            alt=11.0,
            angle=None,
            epoch_time=0,
            fix=telemetry.GPSFix.FIX_2D,
            precision=2.0,
            ground_speed=6.0,
        ),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.GOPRO,
        points=points,
    )
    camm_info = uploader.VideoUploader.prepare_camm_info(metadata)

    # Should stay in mini_gps (type 5)
    assert camm_info.gps is None
    assert camm_info.mini_gps is not None
    assert len(camm_info.mini_gps) == 2


def test_prepare_camm_info_gpspoint_no_fix():
    """GPSPoint with epoch_time but fix=None should infer fix type from altitude."""
    point_with_alt = telemetry.GPSPoint(
        time=0.0,
        lat=37.7749,
        lon=-122.4194,
        alt=10.0,
        angle=None,
        epoch_time=1706000000.0,
        fix=None,
        precision=None,
        ground_speed=None,
    )
    point_without_alt = telemetry.GPSPoint(
        time=1.0,
        lat=37.7750,
        lon=-122.4195,
        alt=None,
        angle=None,
        epoch_time=1706000001.0,
        fix=None,
        precision=None,
        ground_speed=None,
    )
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.GOPRO,
        points=[point_with_alt, point_without_alt],
    )
    camm_info = uploader.VideoUploader.prepare_camm_info(metadata)

    assert camm_info.gps is not None
    assert len(camm_info.gps) == 2
    # With altitude -> 3D fix
    assert camm_info.gps[0].gps_fix_type == 3
    # Without altitude -> 2D fix
    assert camm_info.gps[1].gps_fix_type == 2


def test_prepare_camm_info_mixed_point_types():
    """Test that mixed point types are correctly routed."""
    points: T.List[geo.Point] = [
        # CAMMGPSPoint -> gps
        telemetry.CAMMGPSPoint(
            time=0.0,
            lat=37.7749,
            lon=-122.4194,
            alt=10.0,
            angle=None,
            time_gps_epoch=1706000000.0,
            gps_fix_type=3,
            horizontal_accuracy=1.0,
            vertical_accuracy=2.0,
            velocity_east=0.1,
            velocity_north=0.2,
            velocity_up=0.3,
            speed_accuracy=0.5,
        ),
        # GPSPoint with epoch_time -> converted to CAMMGPSPoint -> gps
        telemetry.GPSPoint(
            time=1.0,
            lat=37.7750,
            lon=-122.4195,
            alt=11.0,
            angle=None,
            epoch_time=1706000001.0,
            fix=telemetry.GPSFix.FIX_3D,
            precision=1.5,
            ground_speed=5.0,
        ),
        # GPSPoint without epoch_time -> mini_gps
        telemetry.GPSPoint(
            time=2.0,
            lat=37.7751,
            lon=-122.4196,
            alt=12.0,
            angle=None,
            epoch_time=None,
            fix=telemetry.GPSFix.FIX_3D,
            precision=1.5,
            ground_speed=5.0,
        ),
        # geo.Point -> mini_gps
        geo.Point(
            time=3.0,
            lat=37.7752,
            lon=-122.4197,
            alt=13.0,
            angle=None,
        ),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.CAMM,
        points=points,
    )
    camm_info = uploader.VideoUploader.prepare_camm_info(metadata)

    # 2 points in gps (CAMMGPSPoint + converted GPSPoint)
    assert camm_info.gps is not None
    assert len(camm_info.gps) == 2
    assert camm_info.gps[0].time_gps_epoch == 1706000000.0
    assert camm_info.gps[1].time_gps_epoch == 1706000001.0

    # 2 points in mini_gps (GPSPoint without epoch + geo.Point)
    assert camm_info.mini_gps is not None
    assert len(camm_info.mini_gps) == 2


def test_prepare_camm_info_gpspoint_roundtrip():
    """GPSPoint with epoch_time should round-trip through CAMM encode/decode with timestamp preserved."""
    points = [
        telemetry.GPSPoint(
            time=0.0,
            lat=37.7749,
            lon=-122.4194,
            alt=10.0,
            angle=None,
            epoch_time=1706000000.0,
            fix=telemetry.GPSFix.FIX_3D,
            precision=1.5,
            ground_speed=5.0,
        ),
        telemetry.GPSPoint(
            time=1.0,
            lat=37.7750,
            lon=-122.4195,
            alt=11.0,
            angle=None,
            epoch_time=1706000001.0,
            fix=telemetry.GPSFix.FIX_3D,
            precision=2.0,
            ground_speed=6.0,
        ),
    ]
    metadata = types.VideoMetadata(
        Path(""),
        filetype=types.FileType.GOPRO,
        points=points,
    )
    x = encode_decode_empty_camm_mp4(metadata)

    # Should come back as CAMMGPSPoint with epoch time preserved
    assert len(x.points) == 2
    for original, decoded in zip(points, x.points):
        assert isinstance(decoded, telemetry.CAMMGPSPoint)
        decoded_camm = T.cast(telemetry.CAMMGPSPoint, decoded)
        assert abs(original.epoch_time - decoded_camm.time_gps_epoch) < 10e-6
        assert abs(original.lat - decoded_camm.lat) < 10e-6
        assert abs(original.lon - decoded_camm.lon) < 10e-6
