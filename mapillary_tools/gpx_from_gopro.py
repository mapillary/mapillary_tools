#!/usr/bin/env python

import datetime
import os
from ffmpeg import extract_stream, get_ffprobe
from gpmf import parse_bin, interpolate_times
from geo import write_gpx

# author https://github.com/stilldavid

'''
Pulls data out of a GoPro 5+ recording while GPS was enabled.
'''


def extract_bin(path):
    info = get_ffprobe(path)

    format_name = info['format']['format_name'].lower()
    if 'mp4' not in format_name:
        raise IOError('File must be an mp4')

    stream_id = None
    for stream in info['streams']:
        if ('codec_tag_string' in stream and 'gpmd' in stream['codec_tag_string'].lower()):
            stream_id = stream['index']

    if not stream_id:
        raise IOError('No GoPro metadata track found - was GPS turned on?')

    basename, extension = os.path.splitext(path)
    bin_path = basename + '.bin'

    extract_stream(path, bin_path, stream_id)

    return bin_path


def get_points_from_gpmf(path):
    bin_path = extract_bin(path)

    gpmf_data = parse_bin(bin_path)
    rows = len(gpmf_data)
    points = []

    for i, frame in enumerate(gpmf_data):
        t = frame['time']

        if i < rows - 1:
            next_ts = gpmf_data[i + 1]['time']
        else:
            next_ts = t + datetime.timedelta(seconds=1)

        interpolate_times(frame, next_ts)

        for point in frame['gps']:
            points.append((
                point['time'],
                point['lat'],
                point['lon'],
                point['alt'],
                frame['gps_fix'],
            ))

    return points


def gpx_from_gopro(gopro_video):

    gopro_data = get_points_from_gpmf(gopro_video)

    basename, extension = os.path.splitext(gopro_video)
    gpx_path = basename + '.gpx'

    write_gpx(gpx_path, sorted(gopro_data))

    return gpx_path
