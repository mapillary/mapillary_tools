# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import json
from pathlib import Path

from mapillary_tools.exceptions import MapillaryMetadataValidationError
from mapillary_tools.serializer.description import (
    DescriptionJSONSerializer,
    ImageVideoDescriptionFileSchema,
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
