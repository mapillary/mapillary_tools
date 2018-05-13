#!/usr/bin/env python

import subprocess
import json
import os

# author https://github.com/stilldavid


def get_ffprobe(path):
    '''
    Gets information about a media file
    TODO: use the class in ffprobe.py - why doesn't it use json output?
    '''
    try:
        with open(os.devnull, 'w') as tempf:
            subprocess.check_call(
                ['ffprobe', '-h'], stdout=tempf, stderr=tempf)
    except Exception as e:
        raise IOError('ffprobe not found.')

    if not os.path.isfile(path):
        raise IOError('No such file: ' + path)

    j_str = ""
    try:
        j_str = subprocess.check_output([
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            path
        ])
    except subprocess.CalledProcessError:
        pass
    j_obj = json.loads(j_str)

    return j_obj


def extract_stream(source, dest, stream_id):
    '''
    Get the data out of the file using ffmpeg
    @param filename: mp4 filename
    '''
    if not os.path.isfile(source):
        raise IOError('No such file: ' + source)

    subprocess.check_output([
        'ffmpeg',
        '-i', source,
        '-y',  # overwrite - potentially dangerous
        '-nostats',
        '-loglevel', '0',
        '-codec', 'copy',
        '-map', '0:' + str(stream_id),
        '-f', 'rawvideo',
        dest,
    ])
