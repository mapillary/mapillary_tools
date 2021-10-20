import datetime
import io
import logging
import os
import re
import typing as T

import pynmea2
from pymp4.parser import Box

from .geotag_from_generic import GeotagFromGeneric
from .geotag_from_gpx import GeotagFromGPX
from .. import image_log, types
from ..error import MapillaryGeoTaggingError, MapillaryStationaryBlackVueError
from ..geo import get_max_distance_from_start

LOG = logging.getLogger(__name__)


class GeotagFromBlackVue(GeotagFromGeneric):
    def __init__(
        self,
        image_dir: str,
        source_path: str,
        use_gpx_start_time: bool = False,
        offset_time: float = 0.0,
    ):
        super().__init__()
        self.image_dir = image_dir
        if os.path.isdir(source_path):
            self.blackvue_videos = image_log.get_video_file_list(
                source_path, abs_path=True
            )
        elif os.path.isfile(source_path):
            # it is okay to not suffix with .mp4
            self.blackvue_videos = [source_path]
        else:
            raise RuntimeError(f"The geotag_source_path {source_path} does not exist")
        self.source_path = source_path
        self.use_gpx_start_time = use_gpx_start_time
        self.offset_time = offset_time

    def to_description(self) -> T.List[types.ImageDescriptionFileOrError]:
        descs: T.List[types.ImageDescriptionFileOrError] = []

        images = image_log.get_total_file_list(self.image_dir)
        for blackvue_video in self.blackvue_videos:
            sample_images = filter_video_samples(images, blackvue_video)
            if not sample_images:
                continue

            [points, is_stationary_video] = gpx_from_blackvue(
                blackvue_video, use_nmea_stream_timestamp=False
            )

            if not points:
                message = f"Skipping the BlackVue video {blackvue_video} -- no GPS found in the video"
                for image in sample_images:
                    error = types.describe_error(MapillaryGeoTaggingError(message))
                    descs.append({"error": error, "filename": image})
                continue

            if is_stationary_video:
                message = f"Skipping stationary BlackVue video {blackvue_video}"
                for image in sample_images:
                    error = types.describe_error(
                        MapillaryStationaryBlackVueError(message)
                    )
                    descs.append({"error": error, "filename": image})
                continue

            geotag = GeotagFromGPX(
                self.image_dir,
                sample_images,
                points,
                use_gpx_start_time=self.use_gpx_start_time,
                offset_time=self.offset_time,
            )

            model = find_camera_model(blackvue_video)
            LOG.debug(f"Found BlackVue camera model %s for %s", model, blackvue_video)

            for desc in types.filter_out_errors(geotag.to_description()):
                desc["MAPDeviceMake"] = "Blackvue"
                if model is not None:
                    desc["MAPDeviceModel"] = model.decode("utf-8")
                descs.append(desc)

        return descs


def find_camera_model(video_path) -> T.Optional[bytes]:
    with open(video_path, "rb") as fd:
        fd.seek(0, io.SEEK_END)
        eof = fd.tell()
        fd.seek(0)
        while fd.tell() < eof:
            box = Box.parse_stream(fd)
            if box.type.decode("utf-8") == "free":
                return box.data[29:39]
        return None


def is_sample_of_video(sample_path: str, video_filename: str) -> bool:
    abs_sample_path = os.path.abspath(sample_path)
    video_basename = os.path.basename(video_filename)
    if video_basename == os.path.basename(os.path.dirname(abs_sample_path)):
        sample_basename = os.path.basename(sample_path)
        root, _ = os.path.splitext(video_basename)
        return sample_basename.startswith(root + "_")
    return False


def filter_video_samples(images: T.List[str], video_path: str) -> T.List[str]:
    return [image for image in images if is_sample_of_video(image, video_path)]


def get_points_from_bv(path, use_nmea_stream_timestamp=False) -> T.List[types.GPXPoint]:
    points = []
    with open(path, "rb") as fd:
        fd.seek(0, io.SEEK_END)
        eof = fd.tell()
        fd.seek(0)
        date = None

        first_gps_date: T.Optional[datetime.date] = None
        first_gps_time: T.Optional[datetime.time] = None
        found_first_gps_date = False
        found_first_gps_time = False

        while fd.tell() < eof:
            box = Box.parse_stream(fd)

            if box.type.decode("utf-8") == "free":
                length = len(box.data)
                offset = 0
                while offset < length:
                    newb = Box.parse(box.data[offset:])
                    if newb.type.decode("utf-8") == "gps":
                        lines = newb.data

                        # Parse GPS trace
                        for line_bytes in lines.splitlines():
                            line = line_bytes.decode("utf-8")
                            m = line.lstrip("[]0123456789")
                            # this utc millisecond timestamp seems to be the camera's
                            # todo: unused?
                            # match = re.search('\[([0-9]+)\]', l)
                            # if match:
                            #     utcdate = match.group(1)

                            # By default, use camera timestamp. Only use GPS Timestamp if camera was not set up correctly and date/time is wrong
                            if not use_nmea_stream_timestamp:
                                if "$GPGGA" in m:
                                    match = re.search("\[([0-9]+)\]", line)
                                    if match:
                                        epoch_in_local_time = match.group(1)

                                    camera_date = datetime.datetime.utcfromtimestamp(
                                        int(epoch_in_local_time) / 1000.0
                                    )
                                    data = pynmea2.parse(m)
                                    if data.is_valid:
                                        if not found_first_gps_time:
                                            first_gps_time = data.timestamp
                                            found_first_gps_time = True
                                        lat, lon, alt = (
                                            data.latitude,
                                            data.longitude,
                                            data.altitude,
                                        )
                                        points.append((camera_date, lat, lon, alt))

                            if use_nmea_stream_timestamp or not found_first_gps_date:
                                if "GPRMC" in m:
                                    try:
                                        data = pynmea2.parse(m)
                                        if data.is_valid:
                                            date = data.datetime.date()
                                            if not found_first_gps_date:
                                                first_gps_date = date
                                    except pynmea2.ChecksumError:
                                        # There are often Checksum errors in the GPS stream, better not to show errors to user
                                        pass
                                    except Exception:
                                        LOG.warning(
                                            "Warning: Error in parsing gps trace to extract date information, nmea parsing failed"
                                        )
                            if use_nmea_stream_timestamp:
                                if "$GPGGA" in m:
                                    try:
                                        data = pynmea2.parse(m)
                                        if data.is_valid:
                                            lat, lon, alt = (
                                                data.latitude,
                                                data.longitude,
                                                data.altitude,
                                            )
                                            if not date:
                                                timestamp = data.timestamp
                                            else:
                                                timestamp = datetime.datetime.combine(
                                                    date, data.timestamp
                                                )
                                            points.append((timestamp, lat, lon, alt))

                                    except Exception as e:
                                        LOG.error(
                                            f"Error in parsing GPS trace to extract time and GPS information, nmea parsing failed",
                                            exc_info=e,
                                        )

                        # If there are no points after parsing just return empty vector
                        if not points:
                            return []

                        # After parsing all points, fix timedate issues
                        if not use_nmea_stream_timestamp:
                            # If we use the camera timestamp, we need to get the timezone offset, since Mapillary backend expects UTC timestamps
                            first_gps_timestamp = datetime.datetime.combine(
                                T.cast(datetime.date, first_gps_date),
                                T.cast(datetime.time, first_gps_time),
                            )
                            delta_t = points[0][0] - first_gps_timestamp
                            if delta_t.days > 0:
                                hours_diff_to_utc = round(
                                    delta_t.total_seconds() / 3600
                                )
                            else:
                                hours_diff_to_utc = (
                                    round(delta_t.total_seconds() / 3600) * -1
                                )
                            utc_points = []
                            for idx, point in enumerate(points):
                                delay_compensation = datetime.timedelta(
                                    seconds=-1.8
                                )  # Compensate for solution age when location gets timestamped by camera clock. Value is empirical from various cameras/recordings
                                new_timestamp = (
                                    points[idx][0]
                                    + datetime.timedelta(hours=hours_diff_to_utc)
                                    + delay_compensation
                                )
                                lat = points[idx][1]
                                lon = points[idx][2]
                                alt = points[idx][3]
                                utc_points.append((new_timestamp, lat, lon, alt))

                            points = utc_points
                            points.sort()

                        else:
                            # add date to points that don't have it yet, because GPRMC message came later
                            utc_points = []
                            for idx, point in enumerate(points):
                                if not isinstance(points[idx][0], datetime.datetime):
                                    timestamp = datetime.datetime.combine(
                                        T.cast(datetime.date, first_gps_date),
                                        T.cast(datetime.time, points[idx][0]),
                                    )
                                else:
                                    timestamp = points[idx][0]
                                lat = points[idx][1]
                                lon = points[idx][2]
                                alt = points[idx][3]
                                utc_points.append((timestamp, lat, lon, alt))

                            points = utc_points
                            points.sort()

                    offset += newb.end

                break

        return [types.GPXPoint(time=p[0], lat=p[1], lon=p[2], alt=p[3]) for p in points]


def is_video_stationary(max_distance_from_start) -> bool:
    radius_threshold = 10
    accumulated_distance_threshold = 20
    return (
        max_distance_from_start < radius_threshold
        or accumulated_distance_threshold < accumulated_distance_threshold
    )


def gpx_from_blackvue(
    bv_video: str, use_nmea_stream_timestamp=False
) -> T.Tuple[T.List[types.GPXPoint], bool]:
    points = get_points_from_bv(bv_video, use_nmea_stream_timestamp)
    if not points:
        return points, True
    return points, is_video_stationary(get_max_distance_from_start(points))
