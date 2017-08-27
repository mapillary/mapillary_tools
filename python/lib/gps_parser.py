#!/usr/bin/python

import sys
import os
import datetime
import time
from lib.geo import gpgga_to_dms, utc_to_localtime

try:
    import gpxpy
    import pynmea2
except ImportError as error:
    print error

'''
Methods for parsing gps data from various file format e.g. GPX, NMEA, SRT.
'''


def get_lat_lon_time_from_gpx(gpx_file, local_time=True):
    '''
    Read location and time stamps from a track in a GPX file.

    Returns a list of tuples (time, lat, lon).

    GPX stores time in UTC, by default we assume your camera used the local time
    and convert accordingly.
    '''
    with open(gpx_file, 'r') as f:
        gpx = gpxpy.parse(f)

    points = []
    if len(gpx.tracks)>0:
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    t = utc_to_localtime(point.time) if local_time else point.time
                    points.append( (t, point.latitude, point.longitude, point.elevation) )
    if len(gpx.waypoints) > 0:
        for point in gpx.waypoints:
            t = utc_to_localtime(point.time) if local_time else point.time
            points.append( (t, point.latitude, point.longitude, point.elevation) )

    # sort by time just in case
    points.sort()

    return points


def get_lat_lon_time_from_nmea(nmea_file, local_time=True):
    '''
    Read location and time stamps from a track in a NMEA file.

    Returns a list of tuples (time, lat, lon).

    GPX stores time in UTC, by default we assume your camera used the local time
    and convert accordingly.
    '''
    with open(nmea_file, "r") as f:
        lines = f.readlines()
        lines = [l.rstrip("\n\r") for l in lines]

    points = []
    for l in lines:
        if "GPRMC" in l:
            data = pynmea2.parse(l)
            date = data.datetime.date()

        if "$GPGGA" in l:
            data = pynmea2.parse(l)
            timestamp = datetime.datetime.combine(date, data.timestamp)
            lat, lon, alt = data.latitude, data.longitude, data.altitude
            points.append((timestamp, lat, lon, alt))

    points.sort()
    return points