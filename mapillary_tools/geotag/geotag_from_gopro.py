import datetime
import logging
import os
import tempfile
import typing as T

from tqdm import tqdm

from .geotag_from_gpx import GeotagFromGPXWithProgress
from .geotag_from_generic import GeotagFromGeneric
from .gpmf import parse_bin, interpolate_times
from . import utils as geotag_utils
from ..geo import get_max_distance_from_start, gps_distance, pairwise
from .. import types, ffmpeg, exceptions, utils


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
            self.videos = utils.get_video_file_list(source_path, abs_path=True)
        else:
            # it is okay to not suffix with .mp4
            self.videos = [source_path]
        self.use_gpx_start_time = use_gpx_start_time
        self.offset_time = offset_time
        super().__init__()

    def to_description(self) -> T.List[types.ImageDescriptionFileOrError]:
        descs: T.List[types.ImageDescriptionFileOrError] = []

        images = utils.get_image_file_list(self.image_dir)
        for video in self.videos:
            LOG.debug("Processing GoPro video: %s", video)

            sample_images = utils.filter_video_samples(images, video)
            LOG.debug(
                "Found %d sample images from video %s",
                len(sample_images),
                video,
            )

            if not sample_images:
                continue

            points = get_points_from_gpmf(video)

            # bypass empty points to raise MapillaryGPXEmptyError
            if points and geotag_utils.is_video_stationary(
                get_max_distance_from_start([(p.lat, p.lon) for p in points])
            ):
                LOG.warning(
                    "Fail %d sample images due to stationary video %s",
                    len(sample_images),
                    video,
                )
                for image in sample_images:
                    err = types.describe_error(
                        exceptions.MapillaryStationaryVideoError(
                            "Stationary GoPro video"
                        )
                    )
                    descs.append({"error": err, "filename": image})
                continue

            with tqdm(
                total=len(sample_images),
                desc=f"Interpolating {os.path.basename(video)}",
                unit="images",
                disable=LOG.getEffectiveLevel() <= logging.DEBUG,
            ) as pbar:
                geotag = GeotagFromGPXWithProgress(
                    self.image_dir,
                    sample_images,
                    points,
                    use_gpx_start_time=self.use_gpx_start_time,
                    offset_time=self.offset_time,
                    progress_bar=pbar,
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


if __name__ == "__main__":
    import sys

    points = get_points_from_gpmf(sys.argv[1])
    gpx = geotag_utils.convert_points_to_gpx(points)
    print(gpx.to_xml())

    LOG.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    LOG.addHandler(handler)
    LOG.info(
        "Stationary: %s",
        geotag_utils.is_video_stationary(
            get_max_distance_from_start([(p.lat, p.lon) for p in points])
        ),
    )
    distance = sum(
        gps_distance((cur.lat, cur.lon), (nex.lat, nex.lon))
        for cur, nex in pairwise(points)
    )
    LOG.info("Total distance: %f", distance)
