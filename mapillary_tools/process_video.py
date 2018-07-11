import os
import datetime
from ffprobe import FFProbe
import uploader
import processing
import sys

from exif_write import ExifEdit
from exif_read import ExifRead
ZERO_PADDING = 6
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT_2 = "%Y-%m-%dT%H:%M:%S.000000Z"


def timestamp_from_filename(filename,
                            start_time,
                            interval=1,
                            adjustment=1.0):
    seconds = (int(filename.lstrip("0").rstrip(".jpg"))) * \
        interval * adjustment
    return start_time + datetime.timedelta(seconds=seconds)


def timestamps_from_filename(full_image_list,
                             start_time,
                             interval=1,
                             adjustment=1.0):
    capture_times = []
    for image in full_image_list:
        capture_times.append(timestamp_from_filename(os.path.basename(image),
                                                     start_time,
                                                     interval,
                                                     adjustment))
    return capture_times


def sample_video(video_file,
                 import_path,
                 geotag_source,
                 video_sample_interval,
                 video_start_time=None,
                 video_duration_ratio=1.0,
                 verbose=False):

    # basic check for all
    import_path = os.path.abspath(import_path)
    if not os.path.isdir(import_path):
        print("Error, import directory " + import_path + " doesnt not exist, exiting...")
        sys.exit()

    # command specific checks
    video_file = os.path.abspath(video_file) if video_file else None
    if not video_file:
        print("Error, video file " + video_file + " does not exist, exiting...")
        sys.exit()

    if os.path.isdir(video_file):
        # if we pass a directory, process each individually then combine the gpx files
        if geotag_source != 'blackvue':
            sys.exit('not sure what to do with a directory of video files that are not blackvue')

        video_list = uploader.get_video_file_list(video_file)
        for video in video_list:
            filename = os.path.splitext(os.path.basename(video))[0]
            extract_frames(video,
                           os.path.join(import_path, filename),
                           video_sample_interval,
                           video_start_time,
                           video_duration_ratio,
                           verbose)
    else:
        # single video file
        extract_frames(video_file,
                       import_path,
                       video_sample_interval,
                       video_start_time,
                       video_duration_ratio,
                       verbose)

def extract_frames(video_file,
                   import_path,
                   video_sample_interval,
                   video_start_time=None,
                   video_duration_ratio=1.0,
                   verbose=False):

    print 'extracting frames from', video_file

    # check video logs
    video_upload = processing.video_upload(video_file, import_path, verbose)

    if video_upload:
        return

    video_file = video_file.replace(" ", "\ ")
    s = "ffmpeg -i {} -loglevel quiet -vf fps=1/{} -qscale 1 {}/%0{}d.jpg".format(
        video_file, video_sample_interval, import_path, ZERO_PADDING)
    os.system(s)

    if video_start_time:
        video_start_time = datetime.datetime.utcfromtimestamp(
            video_start_time / 1000.)
    else:
        video_start_time = get_video_start_time(video_file)
        if not video_start_time:
            print("Warning, video start time not provided and could not be \
                   extracted from the video file, default video start time set \
                   to 0 milliseconds since UNIX epoch.")
            video_start_time = datetime.datetime.utcfromtimestamp(0)

    insert_video_frame_timestamp(import_path,
                                 video_start_time,
                                 video_sample_interval,
                                 video_duration_ratio,
                                 verbose)

    processing.create_and_log_video_process(video_file, import_path)


def get_video_duration(video_file):
    """Get video duration in seconds"""
    return float(FFProbe(video_file).video[0].duration)


def insert_video_frame_timestamp(import_path, start_time, sample_interval, duration_ratio=1.0, verbose=False):

    # get list of file to process
    frame_list = uploader.get_total_file_list(import_path)

    if not len(frame_list):
        if verbose:
            print("No video frames were sampled.")
        return

    video_frame_timestamps = timestamps_from_filename(frame_list,
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
            if verbose:
                print("Could not insert timestamp into video frame " +
                      os.path.basename(image)[:-4])
            continue


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
