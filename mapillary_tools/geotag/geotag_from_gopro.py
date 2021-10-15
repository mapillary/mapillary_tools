import datetime
import logging
import os
import tempfile
import typing as T

from .. import types, image_log, ffmpeg
from .geotag_from_blackvue import filter_video_samples
from .geotag_from_gpx import GeotagFromGPX
from .geotag_from_generic import GeotagFromGeneric
from .gpmf import parse_bin, interpolate_times


LOG = logging.getLogger(__name__)


class GeotagFromGoPro(GeotagFromGeneric):
    def __init__(
        self,
        image_dir: str,
        source_path: str,
        use_gpx_start_time: bool = False,
        offset_time: float = 0.0,
    ):
        self.image_dir = image_dir
        if os.path.isdir(source_path):
            self.videos = image_log.get_video_file_list(source_path, abs_path=True)
        elif os.path.isfile(source_path):
            # it is okay to not suffix with .mp4
            self.videos = [source_path]
        else:
            raise RuntimeError(f"The geotag_source_path {source_path} does not exist")
        self.use_gpx_start_time = use_gpx_start_time
        self.offset_time = offset_time
        super().__init__()

    def to_description(self) -> T.List[types.FinalImageDescriptionOrError]:
        descs = []

        images = image_log.get_total_file_list(self.image_dir)
        for video in self.videos:
            sample_images = filter_video_samples(images, video)
            if not sample_images:
                continue
            points = get_points_from_gpmf(video)
            geotag = GeotagFromGPX(
                self.image_dir,
                sample_images,
                points,
                use_gpx_start_time=self.use_gpx_start_time,
                offset_time=self.offset_time,
            )
            descs.extend(geotag.to_description())

        return descs


def extract_and_parse_bin(path: str) -> T.List:
    info = ffmpeg.probe_video_format_and_streams(path)

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

    with tempfile.NamedTemporaryFile() as tmp:
        LOG.debug("Extracting GoPro stream %s to %s", stream_id, tmp.name)
        ffmpeg.extract_stream(path, tmp.name, stream_id)
        LOG.debug("Parsing GoPro GPMF %s", tmp.name)
        return parse_bin(tmp.name)


def get_points_from_gpmf(path: str) -> T.List[types.GPXPoint]:
    gpmf_data = extract_and_parse_bin(path)

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
