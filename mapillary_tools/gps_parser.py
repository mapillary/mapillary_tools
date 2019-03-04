#!/usr/bin/python

import sys
import os
import datetime
import dateutil.tz
import time
from geo import gpgga_to_dms, utc_to_localtime

try:
    import gpxpy
    import pynmea2
except ImportError as error:
    print error

'''
Methods for parsing gps data from various file format e.g. GPX, NMEA, SRT.
'''


def get_lat_lon_time_from_gpx(gpx_file):
    '''
    Read location and time stamps from a track in a GPX file.

    Returns a list of tuples (time, lat, lon) with proper timezone
    information for the timestamps; and the timezone information
    recovered from the GPX file if any.
    '''
    with open(gpx_file, 'r') as f:
        gpx = gpxpy.parse(f)

    points = []
    tzinfo = None
    if len(gpx.tracks) > 0:
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    if point.time.tzinfo is None:
                        # By default timestamps are in the UTC timezone
                        point.time = point.time.replace(tzinfo=dateutil.tz.UTC)
                    elif tzinfo is None:
                        tzinfo = point.time.tzinfo
                    elif tzinfo.utcoffset(point.time) != point.time.utcoffset():
                        print("{0} contains inconsistent timezone information: {1} != {2}".format(gpx_file, tzinfo, point.time.tzinfo))
                    points.append((point.time, point.latitude, point.longitude, point.elevation))
    if len(gpx.waypoints) > 0:
        for point in gpx.waypoints:
            if point.time.tzinfo is None:
                # By default timestamps are in the UTC timezone
                point.time = point.time.replace(tzinfo=dateutil.tz.UTC)
            elif tzinfo is None:
                tzinfo = point.time.tzinfo
            elif tzinfo.utcoffset(point.time) != point.time.utcoffset():
                print("{0} contains inconsistent timezone information: {1} != {2}".format(gpx_file, tzinfo, point.time.tzinfo))
            points.append((point.time, point.latitude, point.longitude, point.elevation))
    if tzinfo is not None and \
       tzinfo.utcoffset(points[0][0]).total_seconds() == 0:
        # UTC timestamps are the default in GPX files so this does not mean
        # the trace was taken in that timezone.
        tzinfo = None

    # sort by time just in case
    points.sort()

    return points, tzinfo


def get_lat_lon_time_from_nmea(nmea_file):
    '''
    Read location and time stamps from a track in a NMEA file.

    Returns a list of tuples (time, lat, lon) with proper timezone
    information for the timestamps; and the timezone information
    recovered from the NMEA file if any.
    '''
    with open(nmea_file, "r") as f:
        lines = f.readlines()
        lines = [l.rstrip("\n\r") for l in lines]

    # Get initial date
    for l in lines:
        if "GPRMC" in l:
            data = pynmea2.parse(l)
            date = data.datetime.date()
            break

    # Parse GPS trace
    points = []
    for l in lines:
        if "GPRMC" in l:
            data = pynmea2.parse(l)
            date = data.datetime.date()

        if "$GPGGA" in l:
            data = pynmea2.parse(l)
            # Timestamps are always in the UTC timezone for GPGGA records
            timestamp = datetime.datetime.combine(date, data.timestamp).replace(tzinfo=dateutil.tz.UTC)
            lat, lon, alt = data.latitude, data.longitude, data.altitude
            points.append((timestamp, lat, lon, alt))

    points.sort()

    # Only the $GPZDA records have timezone information so return None
    return points, None
