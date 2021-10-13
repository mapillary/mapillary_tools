import datetime
import os
import typing as T

from .. import types, image_log
from ..ffmpeg import extract_stream, get_ffprobe
from .geotag_from_blackvue import filter_video_samples
from .geotag_from_gpx import GeotagFromGPX
from .geotag_from_generic import GeotagFromGeneric
from .gpmf import parse_bin, interpolate_times


class GeotagFromGoPro(GeotagFromGeneric):
    def __init__(self, image_dir: str, source_path: str):
        self.image_dir = image_dir
        if os.path.isdir(source_path):
            self.videos = image_log.get_video_file_list(source_path, abs_path=True)
        elif os.path.isfile(source_path):
            # FIXME: make sure it is mp4
            self.videos = [source_path]
        else:
            raise RuntimeError(f"The geotag_source_path {source_path} does not exist")
        super().__init__()

    def to_description(self) -> T.List[types.FinalImageDescriptionOrError]:
        descs = []

        images = image_log.get_total_file_list(self.image_dir)
        for video in self.videos:
            sample_images = filter_video_samples(images, video)
            if not sample_images:
                continue
            points = get_points_from_gpmf(video)
            geotag = GeotagFromGPX(self.image_dir, sample_images, points)
            descs.extend(geotag.to_description())

        return descs


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


def get_points_from_gpmf(path: str) -> T.List[types.GPXPoint]:
    bin_path = extract_bin(path)

    gpmf_data = parse_bin(bin_path)
    rows = len(gpmf_data)

    points: T.List[types.GPXPoint] = []
    for i, frame in enumerate(gpmf_data):
        t = frame["time"]

        if i < rows - 1:
            next_ts = gpmf_data[i + 1]["time"]
        else:
            next_ts = t + datetime.timedelta(seconds=1)

        interpolate_times(frame, next_ts)

        for point in frame["gps"]:
            points.append(
                types.GPXPoint(
                    time=point["time"],
                    lat=point["lat"],
                    lon=point["lon"],
                    alt=point["alt"],
                    # frame["gps_fix"],
                )
            )

    return points
