import typing as T

from .. import types
from .simple_mp4_parser import parse_boxes
from .geotag_from_blackvue import _parse_gps_box
from . import utils as geotag_utils


def find_camera_model(path: str) -> str:
    with open(path, "rb") as fp:
        for header, stream in parse_boxes(fp):
            if header.type == b"free":
                return parse_camera_model_from_free_box(stream, maxsize=header.maxsize)
    return ""


def parse_camera_model_from_free_box(stream: T.BinaryIO, maxsize: int) -> str:
    for h, s in parse_boxes(stream, maxsize=maxsize):
        if h.type == b"cprt":
            cprt = s.read(h.maxsize)
            # An example cprt: b' Pittasoft Co., Ltd.;DR900S-1CH;'
            fields = cprt.split(b";")
            if 2 <= len(fields):
                model: bytes = fields[1]
                if model:
                    try:
                        return model.decode("utf8")
                    except UnicodeDecodeError:
                        return ""
            else:
                return ""
    return ""


def parse_gps_from_free_box(
    stream: T.BinaryIO, maxsize: int
) -> T.Optional[T.List[types.GPXPoint]]:
    points = None
    for h, s in parse_boxes(stream, maxsize=maxsize):
        if h.type == b"gps ":
            gps_data = s.read(h.maxsize)
            if points is None:
                points = []
            points.extend(_parse_gps_box(gps_data, False))
    return points


def parse_gps_points(path: str) -> T.List[types.GPXPoint]:
    points = None

    with open(path, "rb") as fp:
        for header, stream in parse_boxes(fp):
            if header.type == b"free":
                points = parse_gps_from_free_box(stream, maxsize=header.maxsize)
                if points is not None:
                    break

    if points is None:
        points = []

    points.sort()

    return [types.GPXPoint(time=p[0], lat=p[1], lon=p[2], alt=p[3]) for p in points]


if __name__ == "__main__":
    import sys, os
    from .. import utils

    def _concert(path: str):
        points = parse_gps_points(path)
        gpx = geotag_utils.convert_points_to_gpx(points)
        model = find_camera_model(path)
        gpx.description = f"Extracted from {model}"
        print(gpx.to_xml())

    for path in sys.argv[1:]:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                _concert(p)
        else:
            _concert(path)
