import json

from mapillary_tools.exceptions import MapillaryMetadataValidationError
from mapillary_tools.types import (
    ImageVideoDescriptionFileSchema,
    validate_and_fail_desc,
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
        },
        {
            "MAPLatitude": -90.1,
            "MAPLongitude": -1,
            "MAPCaptureTime": "1020_01_02_11_33_13_123",
            "filename": "foo",
            "filetype": "image",
        },
        {
            "MAPLatitude": 1,
            "MAPLongitude": -180.2,
            "MAPCaptureTime": "3020_01_02_11_12_13_000",
            "filename": "foo",
            "filetype": "image",
        },
        {
            "MAPLatitude": -90,
            "MAPLongitude": 180,
            "MAPCaptureTime": "2000_12_00_10_20_10_000",
            "filename": "foo",
            "filetype": "image",
        },
    ]
    errors = 0
    for desc in descs:
        try:
            validate_image_desc(desc)
        except MapillaryMetadataValidationError:
            errors += 1
    assert errors == len(descs)

    validated = [validate_and_fail_desc(desc) for desc in descs]
    actual_errors = [
        desc
        for desc in validated
        if desc["error"]["type"] == "MapillaryMetadataValidationError"
    ]
    assert {
        "'MAPCaptureTime' is a required property",
        "-90.1 is less than the minimum of -90",
        "-180.2 is less than the minimum of -180",
        "time data '2000_12_00_10_20_10_000' does not match format '%Y_%m_%d_%H_%M_%S_%f'",
    } == set(e["error"]["message"] for e in actual_errors)


def test_validate_image_description_schema():
    with open("./schema/image_description_schema.json") as fp:
        schema = json.load(fp)
    assert json.dumps(schema, sort_keys=True) == json.dumps(
        ImageVideoDescriptionFileSchema, sort_keys=True
    )
