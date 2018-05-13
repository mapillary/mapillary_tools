#!/usr/bin/env python

import argparse
import datetime
import gpxpy
import gpxpy.gpx
import os
from lib.ffmpeg import extract_stream, get_ffprobe
from lib.gpmf import parse_bin, interpolate_times

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


def write_gpx(path, data):
    gpx = gpxpy.gpx.GPX()

    gpx_track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(gpx_track)

    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(gpx_segment)

    for point in data:
        gpx_segment.points.append(gpxpy.gpx.GPXTrackPoint(
            point[1], point[2], elevation=point[3], time=point[0]))

    with open(path, "w") as f:
        f.write(gpx.to_xml())


'''
used over in geotag_video.py
'''


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


def get_args():
    parser = argparse.ArgumentParser(
        description='Extract geospatial information from a GoPro mp4 file')
    parser.add_argument('path', help='path to .mp4 file')
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    args = get_args()
    path = args.path

    gopro_data = get_points_from_gpmf(path)

    basename, extension = os.path.splitext(path)
    gpx_path = basename + '.gpx'

    write_gpx(gpx_path, gopro_data)
