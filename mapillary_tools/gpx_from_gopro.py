#!/usr/bin/env python

import datetime
import os
from ffmpeg import extract_stream, get_ffprobe
from gpmf import parse_bin, interpolate_times
from geo import write_gpx

# author https://github.com/stilldavid

'''
Pulls data out of a GoPro 5+ or AZDOME M06p recording while GPS was enabled.
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

    if stream_id == None:
        raise IOError('No GoPro metadata track found - was GPS turned on?')

    basename, _ = os.path.splitext(path)
    bin_path = basename + '.bin'

    handler_name = info['streams'][stream_id]['tags']['handler_name']
    extract_stream(path, bin_path, stream_id)
    return bin_path, handler_name


def get_points_from_gpmf(path):
    bin_path, handler_name = extract_bin(path)
    points = []

    # gopro or azdome m06p
    if 'GoPro MET' in handler_name:
        gpmf_data = parse_bin(bin_path)
        rows = len(gpmf_data)


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
                    point['spd'],
                ))
    elif handler_name == u'\x03gps':
        pos = 0
        old_lat, old_lon = 0, 0
        with open(bin_path,'rb') as fi:
            while len(fi.read(8)) == 8:
                    
                gps_data = fi.read(57)
                #decode azdome gps data
                gps_text = "".join([chr(ord(c)^0xAA) for c in gps_data])
                    
                # AZDOME stores coordinates in format:
                # lat    DDmm.mmmm 
                # lon   DDDmm.mmmm
                    
                lat = float(gps_text[31:33]) + float(gps_text[33:35] + '.' + gps_text[35:39])/60
                if gps_text[30] == 'S':
                    lat *= -1
                lon = float(gps_text[40:43]) + float(gps_text[43:45] + '.' + gps_text[45:49])/60
                if gps_text[39] == 'W':
                    lon *= -1

                ele = float(gps_text[49:54])
    
                date_time = datetime.datetime.strptime(gps_text[:14],'%Y%m%d%H%M%S')        

                spd = float(gps_text[54:57])/3.6

                if lat and lon:
                    if not spd or (old_lat != lat or old_lon != lon):
                        old_lat, old_lon = lat, lon
                        points.append((date_time,lat,lon,ele, 0.0, spd))
    
                pos += 311
                fi.seek(pos)

    return points


def gpx_from_gopro(gopro_video):

    gopro_data = get_points_from_gpmf(gopro_video)

    basename, _ = os.path.splitext(gopro_video)
    gpx_path = basename + '.gpx'

    write_gpx(gpx_path, sorted(gopro_data))

    return gpx_path
