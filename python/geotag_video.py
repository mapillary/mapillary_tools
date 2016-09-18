import os
import sys
import subprocess
import datetime
import argparse
import json
import lib.io as io
import lib.exifedit as exifedit
import lib.geo as geo
from geotag_from_gpx import get_lat_lon_time
from ffprobe import FFProbe

ZERO_PADDING = 6

def sample_video(video_file, image_path, sample_interval):
    """Sample video frame with the specified time interval

    :params video_file: path to the video file
    :params image_path: path to save the sampled images
    :params sample_interval: sample interval in seconds
    """
    io.mkdir_p(image_path)
    s = "ffmpeg -i {} -loglevel quiet -vf fps=1/{} {}/%0{}d.jpg".format(video_path, sample_interval, image_path, ZERO_PADDING)
    os.system(s)

def get_video_duration(video_file):
    """Get video duration in seconds"""
    return float(FFProbe(video_file).video[0].duration)

def list_images(image_path):
    return [s for s in os.listdir(image_path) if s.lower().endswith(".jpg")]

def timestamp_from_filename(filename, sample_interval, start_time, video_duration, offset=0):
    seconds = (int(filename.lstrip("0").rstrip(".jpg"))-1)*sample_interval
    if seconds > video_duration:
        seconds = video_duration
    return start_time + datetime.timedelta(seconds=seconds)

def get_args():
    p = argparse.ArgumentParser(description='Sample and geotag video with location and orientation from GPX file.')
    p.add_argument('video_path', help='File path to the data file that contains the metadata')
    p.add_argument('--image_path', help='Path to save sampled images.', default="video_samples")
    p.add_argument('--sample_interval', help='Time interval for sampled frames in seconds', default=2, type=float)
    p.add_argument('--gps_trace', help='GPS track file')
    p.add_argument('--time_offset', help='Time offset between video and gpx file in seconds', default=0, type=float)
    return p.parse_args()

if __name__ == "__main__":

    args = get_args()
    video_path = args.video_path
    image_path = args.image_path
    sample_interval = float(args.sample_interval)
    gps_trace_file = args.gps_trace
    time_offset = args.time_offset

    # Parse gps trace
    points = get_lat_lon_time(gps_trace_file)
    start_time = points[0][0] + datetime.timedelta(seconds=time_offset)

    # Get duration of the video
    video_duration = get_video_duration(video_path)
    gps_duration = (points[-1][0] - points[0][0])

    # Sample video
    sample_video(video_path, image_path, sample_interval)

    image_list = list_images(image_path)

    # Add EXIF data to sample images
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
                "bearing": bearing
            }
            exifedit.add_exif_data(os.path.join(image_path, im), data)
        except:
            print "Image {} timestamp out of range. Skipping".format(im)
            missing_gps += 1

    print "{} images missing gps".format(missing_gps)
