# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import json
from pathlib import Path

from mapillary_tools import geo, telemetry
from mapillary_tools.exceptions import MapillaryMetadataValidationError
from mapillary_tools.serializer.description import (
    DescriptionJSONSerializer,
    ImageVideoDescriptionFileSchema,
    PointEncoder,
    validate_image_desc,
)


def test_validate_descs_ok():
    descs = [
        {
            "MAPLatitude": 1,
            "MAPLongitude": 2,
            "MAPCaptureTime": "9020_01_02_11_12_13_1",
            "filename": "foo",
            "filetype": "image",
        },
        {
            "MAPLatitude": -90,
            "MAPLongitude": 180,
            "MAPCaptureTime": "1020_01_02_11_33_13_123",
            "filename": "foo",
            "filetype": "image",
        },
        {
            "MAPLatitude": 90,
            "MAPLongitude": -180,
            "MAPCaptureTime": "3020_01_02_11_12_13_000123",
            "filename": "foo",
            "filetype": "image",
        },
    ]
    for desc in descs:
        validate_image_desc(desc)


def test_validate_descs_not_ok():
    descs = [
        {
            "MAPLatitude": 1,
            "MAPLongitude": 2,
            "filename": "foo",
            "filetype": "image",
            "expected_error_message": "'MAPCaptureTime' is a required property",
        },
        {
            "MAPLatitude": -90.1,
            "MAPLongitude": -1,
            "MAPCaptureTime": "1020_01_02_11_33_13_123",
            "filename": "foo",
            "filetype": "image",
            "expected_error_message": "-90.1 is less than the minimum of -90",
        },
        {
            "MAPLatitude": 1,
            "MAPLongitude": -180.2,
            "MAPCaptureTime": "3020_01_02_11_12_13_000",
            "filename": "foo",
            "filetype": "image",
            "expected_error_message": "-180.2 is less than the minimum of -180",
        },
        {
            "MAPLatitude": -90,
            "MAPLongitude": 180,
            "MAPCaptureTime": "2000_12_00_10_20_10_000",
            "filename": "foo",
            "filetype": "image",
            "expected_error_message": "time data '2000_12_00_10_20_10_000' does not match format '%Y_%m_%d_%H_%M_%S_%f'",
        },
    ]
    errors = 0
    for desc in descs:
        expected_error_message = desc.pop("expected_error_message", None)
        try:
            validate_image_desc(desc)
        except MapillaryMetadataValidationError as ex:
            assert expected_error_message == str(ex)
            errors += 1
    assert errors == len(descs)


def test_validate_image_description_schema():
    with open("./schema/image_description_schema.json") as fp:
        schema = json.load(fp)
    assert json.dumps(schema, sort_keys=True) == json.dumps(
        ImageVideoDescriptionFileSchema, sort_keys=True
    )


def test_serialize_empty():
    assert b"[]" == DescriptionJSONSerializer.serialize([])


def test_serialize_image_description_ok():
    desc = [
        {
            "MAPLatitude": 1.2,
            "MAPLongitude": 2.33,
            "MAPCaptureTime": "2020_01_02_11_12_13_100",
            "filename": "foo你好",
            "filetype": "image",
        }
    ]
    metadatas = DescriptionJSONSerializer.deserialize(json.dumps(desc).encode("utf-8"))
    s1 = DescriptionJSONSerializer.serialize(metadatas)
    # Serialization should be deterministic
    s2 = DescriptionJSONSerializer.serialize(metadatas)
    assert s1 == s2
    actual_descs = json.loads(s1)
    assert {**desc[0], "md5sum": None, "filesize": None} == {
        **actual_descs[0],
        "filename": Path(actual_descs[0]["filename"]).name,
    }


def test_encode_base_point():
    p = geo.Point(
        time=1.5, lat=37.7749295, lon=-122.4194155, alt=10.1235, angle=90.1234
    )
    encoded = PointEncoder.encode(p)
    assert len(encoded) == 6
    assert encoded[0] == 1500  # time in ms
    assert encoded[1] == round(-122.4194155, 7)  # lon
    assert encoded[2] == round(37.7749295, 7)  # lat
    assert encoded[3] == round(10.1235, 3)  # alt
    assert encoded[4] == round(90.1234, 3)  # angle
    assert encoded[5] is None  # no GPS epoch time


def test_decode_base_point():
    entry = [1500, -122.4194155, 37.7749295, 10.124, 90.123]
    p = PointEncoder.decode(entry)
    assert type(p) is geo.Point
    assert p.time == 1.5
    assert p.lon == -122.4194155
    assert p.lat == 37.7749295
    assert p.alt == 10.124
    assert p.angle == 90.123


def test_encode_camm_gps_point():
    p = telemetry.CAMMGPSPoint(
        time=2.0,
        lat=37.7749,
        lon=-122.4194,
        alt=15.0,
        angle=180.0,
        time_gps_epoch=1700000001.0,
        gps_fix_type=3,
        horizontal_accuracy=1.5,
        vertical_accuracy=2.0,
        velocity_east=0.5,
        velocity_north=0.3,
        velocity_up=0.1,
        speed_accuracy=0.2,
    )
    encoded = PointEncoder.encode(p)
    assert len(encoded) == 6
    assert encoded[0] == 2000
    assert encoded[5] == 1700000001.0


def test_decode_camm_gps_point():
    entry = [2000, -122.4194, 37.7749, 15.0, 180.0, 1700000001.0]
    p = PointEncoder.decode(entry)
    assert isinstance(p, telemetry.CAMMGPSPoint)
    assert p.time == 2.0
    assert p.lat == 37.7749
    assert p.lon == -122.4194
    assert p.alt == 15.0
    assert p.angle == 180.0
    assert p.time_gps_epoch == 1700000001.0
    assert p.gps_fix_type == 3  # alt is not None


def test_encode_decode_roundtrip_base_point():
    original = geo.Point(time=3.456, lat=40.7128, lon=-74.006, alt=5.5, angle=270.0)
    encoded = PointEncoder.encode(original)
    decoded = PointEncoder.decode(encoded)
    assert type(decoded) is geo.Point
    # time is rounded to ms precision
    assert decoded.time == int(original.time * 1000) / 1000
    assert decoded.lat == round(original.lat, 7)
    assert decoded.lon == round(original.lon, 7)
    assert decoded.alt == round(original.alt, 3)
    assert decoded.angle == round(original.angle, 3)


def test_encode_decode_roundtrip_camm_gps_point():
    original = telemetry.CAMMGPSPoint(
        time=4.0,
        lat=51.5074,
        lon=-0.1278,
        alt=20.0,
        angle=45.0,
        time_gps_epoch=1700000500.0,
        gps_fix_type=3,
        horizontal_accuracy=1.0,
        vertical_accuracy=1.0,
        velocity_east=0.0,
        velocity_north=0.0,
        velocity_up=0.0,
        speed_accuracy=0.0,
    )
    encoded = PointEncoder.encode(original)
    decoded = PointEncoder.decode(encoded)
    assert isinstance(decoded, telemetry.CAMMGPSPoint)
    assert decoded.time_gps_epoch == original.time_gps_epoch


def test_decode_6_element_with_none_gps_epoch():
    entry = [1500, -122.4194, 37.7749, 10.0, 90.0, None]
    p = PointEncoder.decode(entry)
    # Should fall back to plain Point when 6th element is None
    assert type(p) is geo.Point
    assert p.time == 1.5


def test_encode_gps_point_without_epoch():
    p = telemetry.GPSPoint(
        time=5.0,
        lat=35.6762,
        lon=139.6503,
        alt=40.0,
        angle=0.0,
        epoch_time=None,
        fix=None,
        precision=None,
        ground_speed=None,
    )
    encoded = PointEncoder.encode(p)
    # get_gps_epoch_time() returns None, so 6th element is None
    assert len(encoded) == 6
    assert encoded[5] is None
