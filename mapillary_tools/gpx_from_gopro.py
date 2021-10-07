import datetime
import os
import typing as T

from .ffmpeg import extract_stream, get_ffprobe
from .gpmf import parse_bin, interpolate_times
from .types import GPXPoint


def extract_bin(path: str) -> str:
    info = get_ffprobe(path)

    format_name = info["format"]["format_name"].lower()
    if "mp4" not in format_name:
        raise IOError("File must be an mp4")

    stream_id = None
    for stream in info["streams"]:
        if (
            "codec_tag_string" in stream
            and "gpmd" in stream["codec_tag_string"].lower()
        ):
            stream_id = stream["index"]

    if stream_id is None:
        raise IOError("No GoPro metadata track found - was GPS turned on?")

    basename, _ = os.path.splitext(path)
    bin_path = basename + ".bin"

    extract_stream(path, bin_path, stream_id)

    return bin_path


def get_points_from_gpmf(path: str) -> T.List[GPXPoint]:
    bin_path = extract_bin(path)

    gpmf_data = parse_bin(bin_path)
    rows = len(gpmf_data)

    points: T.List[GPXPoint] = []
    for i, frame in enumerate(gpmf_data):
        t = frame["time"]

        if i < rows - 1:
            next_ts = gpmf_data[i + 1]["time"]
        else:
            next_ts = t + datetime.timedelta(seconds=1)

        interpolate_times(frame, next_ts)

        for point in frame["gps"]:
            points.append(
                GPXPoint(
                    time=point["time"],
                    lat=point["lat"],
                    lon=point["lon"],
                    alt=point["alt"],
                    # frame["gps_fix"],
                )
            )

    return points


def gpx_from_gopro(gopro_video: str) -> T.List[GPXPoint]:
    return get_points_from_gpmf(gopro_video)
