#!/usr/bin/env python

import datetime
import os
import io
import sys
import re
import pynmea2
import uploader
from geo import write_gpx

from pymp4.parser import Box
from construct.core import RangeError, ConstError

'''
Pulls geo data out of a BlackVue video files
'''


def get_points_from_bv(path):
    points = []

    fd = open(path, 'rb')

    fd.seek(0, io.SEEK_END)
    eof = fd.tell()
    fd.seek(0)
    date = None
    while fd.tell() < eof:
        try:
            box = Box.parse_stream(fd)
        except RangeError:
            print('error parsing blackvue GPS information, exiting')
            sys.exit(1)
        except ConstError:
            print('error parsing blackvue GPS information, exiting')
            sys.exit(1)

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
                            try:
                                data = pynmea2.parse(m)
                                date = data.datetime.date()
                            except Exception as e:
                                print(
                                    "Error in extracting the gps trace, nmea parsing failed due to {}".format(e))
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
                            try:
                                data = pynmea2.parse(m)
                                date = data.datetime.date()
                            except Exception as e:
                                print(
                                    "Error in parsing gps trace to extract date information, nmea parsing failed due to {}".format(e))
                        if "$GPGGA" in m:
                            try:
                                if not date:
                                    print(
                                        "Error, could not extract date from the video gps trace, exiting...")
                                    sys.exit(1)
                                data = pynmea2.parse(m)
                                timestamp = datetime.datetime.combine(
                                    date, data.timestamp)
                                lat, lon, alt = data.latitude, data.longitude, data.altitude
                                points.append((timestamp, lat, lon, alt))
                            except Exception as e:
                                print(
                                    "Error in parsing gps trace to extract time and gps information, nmea parsing failed due to {}".format(e))

                    points.sort()
                offset += newb.end

            break

    return points


def gpx_from_blackvue(bv_video):
    bv_data = []
    try:
        bv_data = get_points_from_bv(bv_video)
    except Exception as e:
        print(
            "Warning, could not extract gps from video {} due to {}, video will be skipped...".format(bv_video, e))
    basename, extension = os.path.splitext(bv_video)
    gpx_path = basename + '.gpx'

    bv_data.sort(key=lambda x: x[0])

    write_gpx(gpx_path, bv_data)

    return gpx_path
