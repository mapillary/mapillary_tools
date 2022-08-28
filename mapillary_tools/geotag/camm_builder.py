import typing as T

from .. import geo

from . import camm_parser


def build_camm_sample(point: geo.Point) -> bytes:
    return camm_parser.CAMMSampleData.build(
        {
            "type": camm_parser.CAMMType.MIN_GPS.value,
            "data": [
                point.lat,
                point.lon,
                -1.0 if point.alt is None else point.alt,
            ],
        }
    )


def build_camm_samples_from_points():
    pass
