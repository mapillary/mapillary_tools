#!/usr/bin/env python

import os
import gpxpy
import gpxpy.gpx
import argparse
from lib.ffmpeg import extract_stream, get_ffprobe
from lib.gpmf import parse_bin

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
        gpx_segment.points.append(gpxpy.gpx.GPXTrackPoint(point['gps'][0]['lat'], point['gps'][0]['lon'], elevation=point['gps'][0]['alt']))

    print 'Created GPX:', gpx.to_xml()

    '''
    with open(path, "w") as f:
        f.write(gpx)
        '''


def get_points_from_gpmf(path):
    bin_path = extract_bin(path)

    gpmf_data = parse_bin(bin_path)

    points = []

    for point in gpmf_data:
        t = point['time']  # todo: localize with local_time
        # use the first GPS point - we get 18Hz though
        points.append((t, point['gps'][0]['lat'], point['gps'][0]['lon'], point['gps'][0]['alt']))

    return points


def get_args():
    parser = argparse.ArgumentParser(description='Extract geospatial information from a GoPro mp4 file')
    parser.add_argument('path', help='path to .mp4 file')
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    args = get_args()
    path = args.path

    bin_path = extract_bin(path)

    gopro_data = parse_bin(bin_path)

    basename, extension = os.path.splitext(path)
    gpx_path = basename + '.gpx'

    write_gpx(gpx_path, gopro_data)
