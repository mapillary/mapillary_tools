#!/usr/bin/env python

import datetime
import gpxpy
import gpxpy.gpx
import os
import io
import sys
import re
import pynmea2
import uploader

from pymp4.parser import Box
from construct.core import RangeError, ConstError

'''
Pulls geo data out of a BlackVue video files
'''

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


def get_points_from_bv(path):
    points = []

    fd = open(path, 'rb')

    fd.seek(0, io.SEEK_END)
    eof = fd.tell()
    fd.seek(0)

    while fd.tell() < eof:
        try:
            box = Box.parse_stream(fd)
        except RangeError:
            print('error parsing blackvue GPS information, exiting')
            sys.exit()
        except ConstError:
            print('error parsing blackvue GPS information, exiting')
            sys.exit()

        if box.type.decode('utf-8') == 'free':
            length = len(box.data)
            offset = 0
            while offset < length:
                newb = Box.parse(box.data[offset:])
                if newb.type.decode('utf-8') == 'gps':
                    lines = newb.data

                    for l in lines:
                        if "GPRMC" in l:
                            m = l.lstrip('[]0123456789')
                            data = pynmea2.parse(m)
                            date = data.datetime.date()
                            break

                    # Parse GPS trace
                    for l in lines.splitlines():
                        # this utc millisecond timestamp seems to be the camera's
                        # todo: unused?
                        # match = re.search('\[([0-9]+)\]', l)
                        # if match:
                        #     utcdate = match.group(1)

                        m = l.lstrip('[]0123456789')

                        if "GPRMC" in m:
                            data = pynmea2.parse(m)
                            date = data.datetime.date()

                        if "$GPGGA" in m:
                            data = pynmea2.parse(m)
                            timestamp = datetime.datetime.combine(date, data.timestamp)
                            lat, lon, alt = data.latitude, data.longitude, data.altitude
                            points.append((timestamp, lat, lon, alt))

                    points.sort()
                offset += newb.end

            break

    return points


def gpx_from_blackvue(bv_video):
    bv_data = []

    if os.path.isdir(bv_video):
        video_files = uploader.get_video_file_list(bv_video)
        for video in video_files:
            bv_data += get_points_from_bv(video)

        dirname = os.path.dirname(bv_video)
        gpx_path = os.path.join(dirname, 'path.gpx')
    else:
        bv_data = get_points_from_bv(bv_video)
        basename, extension = os.path.splitext(bv_video)
        gpx_path = basename + '.gpx'

    bv_data.sort(key=lambda x: x[0])

    write_gpx(gpx_path, bv_data)

    return gpx_path
