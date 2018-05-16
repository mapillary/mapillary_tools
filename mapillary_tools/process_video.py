import os
import datetime
from ffprobe import FFProbe
import uploader
import processing
ZERO_PADDING = 6
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT_2 = "%Y-%m-%dT%H:%M:%S.000000Z"


def sample_video(video_file,
                 import_path,
                 sample_interval,
                 verbose):
    # check video logs
    video_upload = processing.video_upload(
        video_file, import_path, verbose)

    if video_upload:
        return

    video_file = video_file.replace(" ", "\ ")
    s = "ffmpeg -i {} -loglevel quiet -vf fps=1/{} -qscale 1 {}/%0{}d.jpg".format(
        video_file, sample_interval, import_path, ZERO_PADDING)
    os.system(s)

    processing.create_and_log_video_process(
        video_file, import_path)


def get_video_duration(video_file):
    """Get video duration in seconds"""
    return float(FFProbe(video_file).video[0].duration)


def get_video_start_time(video_file):
    """Get video start time in seconds"""
    try:
        time_string = FFProbe(video_file).video[0].creation_time
        try:
            creation_time = datetime.datetime.strptime(
                time_string, TIME_FORMAT)
        except:
            creation_time = datetime.datetime.strptime(
                time_string, TIME_FORMAT_2)
    except:
        return None
    return creation_time
