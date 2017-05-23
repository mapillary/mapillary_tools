#!/usr/bin/env python

import os
import sys
import subprocess
import datetime
import argparse
import json
import lib.io as io
import lib.exifedit as exifedit
import lib.geo as geo
from lib.gps_parser import get_lat_lon_time_from_gpx, get_lat_lon_time_from_nmea
from lib.ffprobe import FFProbe

ZERO_PADDING = 6
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

def sample_video(video_file, image_path, sample_interval):
    """Sample video frame with the specified time interval

    :params video_file: path to the video file
    :params image_path: path to save the sampled images
    :params sample_interval: sample interval in seconds
    """
    io.mkdir_p(image_path)
    video_file = video_file.replace(" ", "\ ")
    s = "ffmpeg -i {} -loglevel quiet -vf fps=1/{} -qscale 1 {}/%0{}d.jpg".format(video_file, sample_interval, image_path, ZERO_PADDING)
    os.system(s)


def get_video_duration(video_file):
    """Get video duration in seconds"""
    return float(FFProbe(video_file).video[0].duration)


def get_video_start_time(video_file):
    """Get video duration in seconds"""
    try:
        time_string = FFProbe(video_file).video[0].creation_time
        creation_time = datetime.datetime.strptime(time_string, TIME_FORMAT)
    except:
        return None
    return creation_time


def parse_gps_trace(gps_trace_file, local_time=False):
    points = None
    if gps_trace_file.lower().endswith(".gpx"):
        points = get_lat_lon_time_from_gpx(gps_trace_file, local_time)
    elif gps_trace_file.lower().endswith(".nmea"):
        points = get_lat_lon_time_from_nmea(gps_trace_file, local_time)
    elif gps_trace_file.lower().endswith(".srt"):
        pass
    return points


def list_images(image_path):
    return [s for s in os.listdir(image_path) if s.lower().endswith(".jpg")]


def timestamp_from_filename(filename, sample_interval, start_time, video_duration, offset=0):
    seconds = (int(filename.lstrip("0").rstrip(".jpg"))-1)*sample_interval
    if seconds > video_duration:
        seconds = video_duration
    return start_time + datetime.timedelta(seconds=seconds)


def get_args():
    p = argparse.ArgumentParser(description='Sample and geotag video with location and orientation from GPX file.')
    p.add_argument('video_file', help='File path to the data file that contains the metadata')
    p.add_argument('--image_path', help='Path to save sampled images.', default="video_samples")
    p.add_argument('--sample_interval', help='Time interval for sampled frames in seconds', default=2, type=float)
    p.add_argument('--gps_trace', help='GPS track file')
    p.add_argument('--time_offset', help='Time offset between video and gpx file in seconds', default=0, type=float)
    p.add_argument("--skip_sampling", help="Skip video sampling step", action="store_true")
    return p.parse_args()


if __name__ == "__main__":

    args = get_args()
    video_file = args.video_file
    image_path = args.image_path
    sample_interval = float(args.sample_interval)
    gps_trace_file = args.gps_trace
    time_offset = args.time_offset
    make = os.environ.get("MAKE", "none")
    model = os.environ.get("MODEL", "none")

    # Parse gps trace
    local_time = False
    points = parse_gps_trace(gps_trace_file, local_time)

    # Get sync between video and gps trace
    start_time = points[0][0]
    start_time += datetime.timedelta(seconds=time_offset)
    print "Video starts at : {}".format(start_time)
    print "GPS trace starts at: {}".format(points[0][0])

    # Get duration of the video
    video_duration = get_video_duration(video_file)
    gps_duration = (points[-1][0] - points[0][0])

    # Sample video
    if not args.skip_sampling:
        sample_video(video_file, image_path, sample_interval)

    # Add EXIF data to sample images
    image_list = list_images(image_path)
    print "Adding EXIF to {} images".format(len(image_list))

    missing_gps = 0
    for i, im in enumerate(image_list):
        io.progress(i, len(image_list))
        timestamp = timestamp_from_filename(os.path.basename(im),
                                            sample_interval,
                                            start_time,
                                            video_duration,
                                            time_offset)

        try:
            lat, lon, bearing, altitude = geo.interpolate_lat_lon(points, timestamp)
            data = {
                "lat": lat,
                "lon": lon,
                "altitude": altitude,
                "capture_time": timestamp,
                "bearing": bearing,
                "make": make,
                "model": model
            }
            exifedit.add_exif_data(os.path.join(image_path, im), data)
        except Exception as e:
            print e
            print "Image {} timestamp out of range. Skipping".format(im)
            missing_gps += 1

    print "{} image samples with {} images missing gps".format(len(image_list), missing_gps)
