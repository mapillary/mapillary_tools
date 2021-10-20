import typing as T

import jsonschema

from . import types


def feature_collection_schema(features: T.Dict) -> T.Dict:
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": "FeatureCollection"},
            "features": {
                "type": "array",
                "items": features,
            },
        },
    }


def feature_schema(geometry: T.Dict, properties: T.Any) -> T.Dict:
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": "Feature"},
            "properties": properties,
            "geometry_schema": geometry,
        },
    }


def position_schema():
    return {
        "type": "array",
        "items": {
            "type": "number",
        },
    }


def point_schema():
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string"},
            "coordinates": position_schema(),
        },
    }


def single_feature_to_desc(
    feature: T.Dict, quiet=False
) -> T.Optional[types.ImageDescriptionEXIF]:
    input_schema = feature_schema(point_schema(), {})
    if quiet:
        try:
            jsonschema.validate(instance=feature, schema=input_schema)
        except jsonschema.exceptions.ValidationError:
            return None
    lng, lat = feature["geometry"]["coordinates"]
    desc = {
        "MAPLatitude": lng,
        "MAPLongitude": lat,
        **feature["properties"],
    }
    return T.cast(types.ImageDescriptionEXIF, desc)


def feature_collection_to_desc(
    feature_collection: T.Dict,
) -> T.List[types.ImageDescriptionEXIF]:
    input_schema = feature_collection_schema(
        feature_schema(
            point_schema(),
            True,
        )
    )
    jsonschema.validate(instance=feature_collection, schema=input_schema)
    desc = [
        single_feature_to_desc(f, quiet=True) for f in feature_collection["features"]
    ]
    return [d for d in desc if d is not None]


def single_desc_to_feature(
    desc: types.ImageDescriptionEXIF, quiet=False
) -> T.Optional[T.Dict]:
    input_schema = {
        "type": "array",
        "items": types.ImageDescriptionEXIFSchema,
    }
    if quiet:
        try:
            jsonschema.validate(instance=desc, schema=input_schema)
        except jsonschema.exceptions.ValidationError:
            return None
    properties = {**desc}
    del properties["MAPLongitude"]
    del properties["MAPLatitude"]
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [desc["MAPLongitude"], desc["MAPLatitude"]],
        },
        "properties": properties,
    }


def desc_to_feature_collection(desc: T.List[types.ImageDescriptionEXIF]) -> T.Dict:
    features = [single_desc_to_feature(d) for d in desc]
    return {
        "type": "FeatureCollection",
        "features": features,
    }


if __name__ == "__main__":
    import json
    import sys

    with open(sys.argv[1]) as fp:
        descs = json.load(fp)
        feature_collection = desc_to_feature_collection(
            T.cast(T.List[types.ImageDescriptionEXIF], types.filter_out_errors(descs))
        )
        print(json.dumps(feature_collection, indent=4))
