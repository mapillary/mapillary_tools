from ffprobe import FFProbe
import datetime
import os
import processing
import subprocess
import sys
import uploader
from tqdm import tqdm
import logging
import io
import struct

from exif_write import ExifEdit

ZERO_PADDING = 6
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT_2 = "%Y-%m-%dT%H:%M:%S.000000Z"


def timestamp_from_filename(video_filename,
                            filename,
                            start_time,
                            interval=2.0,
                            adjustment=1.0):

    seconds = (int(filename.rstrip(".jpg").replace("{}_".format(
        video_filename), "").lstrip("0")) - 1) * interval * adjustment

    return start_time + datetime.timedelta(seconds=seconds)


def timestamps_from_filename(video_filename,
                             full_image_list,
                             start_time,
                             interval=2.0,
                             adjustment=1.0):
    capture_times = []
    for image in tqdm(full_image_list, desc="Deriving frame capture time"):
        capture_times.append(timestamp_from_filename(video_filename,
                                                     os.path.basename(image),
                                                     start_time,
                                                     interval,
                                                     adjustment))
    return capture_times


def sample_video(video_import_path,
                 import_path,
                 video_sample_interval=2.0,
                 video_start_time=None,
                 video_duration_ratio=1.0,
                 verbose=False,
                 skip_subfolders=False):

    if import_path and not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " does not exist, exiting...")  # ERROR LOG
        sys.exit(1)

    # sanity check
    if not os.path.isdir(video_import_path) and not os.path.isfile(video_import_path):
        print("Error, video path " + video_import_path +
              " does not exist, exiting...")
        sys.exit(1)

    # Adjust the import path
    video_sampling_path = "mapillary_sampled_video_frames"
    video_dirname = video_import_path if os.path.isdir(
        video_import_path) else os.path.dirname(video_import_path)
    import_path = os.path.join(os.path.abspath(import_path), video_sampling_path) if import_path else os.path.join(
        os.path.abspath(video_dirname), video_sampling_path)

    video_list = uploader.get_video_file_list(video_import_path, skip_subfolders) if os.path.isdir(
        video_import_path) else [video_import_path]

    for video in tqdm(video_list, desc="Extracting video frames"):

        per_video_import_path = os.path.join(
            import_path, ".".join(os.path.basename(video).split(".")[:-1]))
        if not os.path.isdir(per_video_import_path):
            os.makedirs(per_video_import_path)

        print("Video sampling path set to {}".format(per_video_import_path))
        # check video logs
        video_upload = processing.video_upload(
            video_import_path, per_video_import_path, verbose)
        if video_upload:
            print("Video {} has already been uploaded, contact support@mapillary for help with reuploading it if neccessary.".format(video))

        extract_frames(video,
                       per_video_import_path,
                       video_sample_interval,
                       video_start_time,
                       video_duration_ratio,
                       verbose)

    processing.create_and_log_video_process(video_import_path, import_path)


def extract_frames(video_file,
                   import_path,
                   video_sample_interval=2.0,
                   video_start_time=None,
                   video_duration_ratio=1.0,
                   verbose=False):

    if verbose:
        # INFO LOG
        print('extracting frames from {}'.format(video_file))

    video_filename = ".".join(os.path.basename(video_file).split(".")[:-1])

    command = [
        'ffmpeg',
        '-i', video_file,
        '-loglevel', 'quiet',
        '-vf', 'fps=1/{}'.format(video_sample_interval),
        '-qscale', '1', '-nostdin'
    ]

    command.append('{}_%0{}d.jpg'.format(os.path.join(
        import_path, video_filename), ZERO_PADDING))
    try:
        subprocess.call(command)
    except OSError as e:
        # ERROR LOG
        print("Error, ffmpeg is not installed or set in the OS system path.")
        sys.exit(1)
    except Exception as e:
        # ERROR LOG
        print("Error, could not extract frames from video {} due to {}".format(
            video_file, e))
        sys.exit(1)

    if video_start_time:
        video_start_time = datetime.datetime.utcfromtimestamp(
            video_start_time / 1000.)
    else:
        video_start_time = get_video_start_time(video_file)
        if not video_start_time:
            # WARNING LOG
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


def get_video_duration(video_file):
    """Get video duration in seconds"""
    try:
        return float(FFProbe(video_file).video[0].duration)
    except Exception as e:
        print("could not extract duration from video {} due to {}".format(video_file, e))
        return None


def insert_video_frame_timestamp(video_filename, video_sampling_path, start_time, sample_interval=2.0, duration_ratio=1.0, verbose=False):

    # get list of file to process
    frame_list = uploader.get_total_file_list(video_sampling_path)

    if not len(frame_list):
        # WARNING LOG
        print("No video frames were sampled.")
        return

    video_frame_timestamps = timestamps_from_filename(video_filename,
                                                      frame_list,
                                                      start_time,
                                                      sample_interval,
                                                      duration_ratio)

    for image, timestamp in tqdm(zip(frame_list,
                                     video_frame_timestamps), desc="Inserting frame capture time"):
        try:
            exif_edit = ExifEdit(image)
            exif_edit.add_date_time_original(timestamp)
            exif_edit.write()
        except:
            # ERROR LOG
            print("Could not insert timestamp into video frame " +
                  os.path.basename(image)[:-4])
            continue


def get_video_end_time(video_file):
    """Get video end time in seconds"""
    if not os.path.isfile(video_file):
        print("Error, video file {} does not exist".format(video_file))
        return None
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


def get_video_start_time(video_file):
    """Get start time in seconds"""
    if not os.path.isfile(video_file):
        print("Error, video file {} does not exist".format(video_file))
        return None
    video_end_time = get_video_end_time(video_file)
    duration = get_video_duration(video_file)
    if video_end_time == None or duration == None:
        return None
    else:
        video_start_time = (
            video_end_time - datetime.timedelta(seconds=duration))
        return video_start_time


def get_video_start_time_blackvue(video_file):
    from pymp4.parser import Box
    with open(video_file, 'rb') as fd:
        fd.seek(0, io.SEEK_END)
        eof = fd.tell()
        fd.seek(0)

        while fd.tell() < eof:
            box = Box.parse_stream(fd)
            if box.type.decode('utf-8') == "moov":
                fd.seek(box.offset + 8, 0)

                size = struct.unpack('>I', fd.read(4))[0]
                typ = fd.read(4)

                fd.seek(4, os.SEEK_CUR)

                creation_time = struct.unpack('>I', fd.read(4))[0]
                modification_time = struct.unpack('>I', fd.read(4))[0]
                time_scale = struct.unpack('>I', fd.read(4))[0]
                duration = struct.unpack('>I', fd.read(4))[0]

                # from documentation
                # in seconds since midnight, January 1, 1904
                video_start_time_epoch = creation_time * 1000 - duration
                epoch_start = datetime.datetime(year=1904, month=1, day=1)
                video_start_time = epoch_start + \
                    datetime.timedelta(milliseconds=video_start_time_epoch)
                return video_start_time
