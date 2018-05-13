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


def timestamp_from_filename(filename,
                            sample_interval,
                            start_time,
                            video_duration,
                            ratio=1.0):
    seconds = (int(filename.lstrip("0").rstrip(".jpg"))) * \
        sample_interval * ratio
    if seconds > video_duration:
        seconds = video_duration
    return start_time + datetime.timedelta(seconds=seconds)


def timestamps_from_filename(full_image_list,
                             video_duration,
                             sample_interval,
                             start_time,
                             duration_ratio):
    capture_times = []
    for image in full_image_list:
        capture_times.append(timestamp_from_filename(os.path.basename(image),
                                                     sample_interval,
                                                     start_time,
                                                     video_duration,
                                                     duration_ratio))
    return capture_times


def process_video():
    # sanity checks for video
    # currently only gpx trace if supported as video gps data
    if geotag_source != "gpx":
        if verbose:
            print(
                "Warning, geotag source not specified to gpx. Currently only gpx trace is supported as the source of video gps data.")
        geotag_source = "gpx"
    if not geotag_source_path or not os.path.isfile(geotag_source_path) or geotag_source_path[-3:] != "gpx":
        print("Error, gpx trace file path not valid or specified. To geotag a video, a valid gpx trace file is required.")
        sys.exit()

    # sample video
    if not skip_sampling:

        process_video.sample_video(video_file,
                                   import_path,  # should all the existing image here be removed prior sampling?
                                   sample_interval)
