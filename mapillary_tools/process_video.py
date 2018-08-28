from ffprobe import FFProbe
import datetime
import os
import processing
import subprocess
import sys
import uploader

from exif_write import ExifEdit

ZERO_PADDING = 6
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT_2 = "%Y-%m-%dT%H:%M:%S.000000Z"


def timestamp_from_filename(video_filename,
                            filename,
                            start_time,
                            interval=2.0,
                            adjustment=1.0):
    seconds = (int(filename.lstrip("0").replace("_{}.jpg".format(video_filename), "")) - 1) * \
        interval * adjustment
    return start_time + datetime.timedelta(seconds=seconds)


def timestamps_from_filename(video_filename,
                             full_image_list,
                             start_time,
                             interval=2.0,
                             adjustment=1.0):
    capture_times = []
    for image in full_image_list:
        capture_times.append(timestamp_from_filename(video_filename,
                                                     os.path.basename(image),
                                                     start_time,
                                                     interval,
                                                     adjustment))
    return capture_times


def sample_video(video_path,
                 import_path,
                 geotag_source=None,
                 video_sample_interval=2.0,
                 video_start_time=None,
                 video_duration_ratio=1.0,
                 verbose=False):

    # basic check for all
    import_path = os.path.abspath(import_path)
    if not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " does not exist, exiting...")
        sys.exit(1)

    # command specific checks
    video_path = os.path.abspath(video_path) if (
        os.path.isfile(video_path) or os.path.isdir(video_path)) else None
    if not video_path:
        print("Error, video path " + video_path + " does not exist, exiting...")
        sys.exit(1)

    # check video logs
    video_upload = processing.video_upload(video_path, import_path, verbose)

    if video_upload:
        return

    if os.path.isdir(video_path):
        # if we pass a directory, process each individually then combine the
        # gpx files
        if geotag_source != 'blackvue':
            print('Processing a set of video files only supported for Blackvue captures, please set the --geotag_source "blackvue" and the --geotag_source_path to the directory of videos captured by Blackvue.')
            sys.exit(1)

        video_list = uploader.get_video_path_list(video_path)
        #count = 0
        for video in video_list:
            extract_frames(video,
                           import_path,
                           video_sample_interval,
                           video_start_time,
                           video_duration_ratio,
                           verbose)
            # count)
            #count = frames + 1
    else:
        # single video file
        extract_frames(video_path,
                       import_path,
                       video_sample_interval,
                       video_start_time,
                       video_duration_ratio,
                       verbose)

    processing.create_and_log_video_process(video_path, import_path)


def extract_frames(video_path,
                   import_path,
                   video_sample_interval=2.0,
                   video_start_time=None,
                   video_duration_ratio=1.0,
                   verbose=False):
                   # start_number=None):

    if verbose:
        print('extracting frames from', video_path)

    video_path = video_path.replace(" ", "\ ")
    video_filename = os.path.basename(video_path).rstrip(".mp4")

    command = [
        'ffmpeg',
        '-i', video_path,
        '-loglevel', 'quiet',
        '-vf', 'fps=1/{}'.format(video_sample_interval),
        '-qscale', '1',
    ]

    command.append('{}/%0{}d_{}.jpg'.format(import_path,
                                            ZERO_PADDING, video_filename))

    subprocess.call(command)

    if video_start_time:
        video_start_time = datetime.datetime.utcfromtimestamp(
            video_start_time / 1000.)
    else:
        video_start_time = get_video_start_time(video_path)
        if not video_start_time:
            print("Warning, video start time not provided and could not be \
                   extracted from the video file, default video start time set \
                   to 0 milliseconds since UNIX epoch.")
            video_start_time = datetime.datetime.utcfromtimestamp(0)

    insert_video_frame_timestamp(video_filename,
                                 import_path,
                                 video_start_time,
                                 video_sample_interval,
                                 video_duration_ratio,
                                 verbose)

    # return len(uploader.get_total_file_list(import_path))


def get_video_duration(video_path):
    """Get video duration in seconds"""
    return float(FFProbe(video_path).video[0].duration)


def insert_video_frame_timestamp(video_filename, import_path, start_time, sample_interval=2.0, duration_ratio=1.0, verbose=False):

    # get list of file to process
    frame_list = uploader.get_total_file_list(import_path)

    if not len(frame_list):
        print("No video frames were sampled.")
        return

    video_frame_timestamps = timestamps_from_filename(video_filename,
                                                      frame_list,
                                                      start_time,
                                                      sample_interval,
                                                      duration_ratio)

    for image, timestamp in zip(frame_list,
                                video_frame_timestamps):
        try:
            exif_edit = ExifEdit(image)
            exif_edit.add_date_time_original(timestamp)
            exif_edit.write()
        except:
            print("Could not insert timestamp into video frame " +
                  os.path.basename(image)[:-4])
            continue


def get_video_start_time(video_path):
    """Get video start time in seconds"""
    try:
        time_string = FFProbe(video_path).video[0].creation_time
        try:
            creation_time = datetime.datetime.strptime(
                time_string, TIME_FORMAT)
        except:
            creation_time = datetime.datetime.strptime(
                time_string, TIME_FORMAT_2)
    except:
        return None
    return creation_time
