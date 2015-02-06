#!/usr/bin/python

import sys
import os
import gpxpy
import datetime
import pyexiv2
import math
import time
from pyexiv2.utils import make_fraction


'''
Script for geotagging images using a gpx file from an external GPS.
Intended as a lightweight tool.

!!! This version needs testing, please report issues.!!!

Uses the capture time in EXIF and looks up an interpolated lat, lon, bearing
for each image, and writes the values to the EXIF of the image.

You can supply a time offset in seconds if the GPS clock and camera clocks are not in sync.

Requires gpxpy, e.g. 'pip install gpxpy'

Requires pyexiv2, see install instructions at http://tilloy.net/dev/pyexiv2/
(or use your favorite installer, e.g. 'brew install pyexiv2').
'''

def utc_to_localtime(utc_time):
    utc_offset_timedelta = datetime.datetime.utcnow() - datetime.datetime.now()
    return utc_time - utc_offset_timedelta


def get_lat_lon_time(gpx_file):
    '''
    Read location and time stamps from a track in a GPX file.

    Returns a list of tuples (time, lat, lon).

    GPX stores time in UTC, assume your camera used the local
    timezone and convert accordingly.
    '''
    with open(gpx_file, 'r') as f:
        gpx = gpxpy.parse(f)

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append( (utc_to_localtime(point.time), point.latitude, point.longitude, point.elevation) )

    # sort by time just in case
    points.sort()

    return points


def compute_bearing(start_lat, start_lon, end_lat, end_lon):
    '''
    Get the compass bearing from start to end.

    Formula from
    http://www.movable-type.co.uk/scripts/latlong.html
    '''
    # make sure everything is in radians
    start_lat = math.radians(start_lat)
    start_lon = math.radians(start_lon)
    end_lat = math.radians(end_lat)
    end_lon = math.radians(end_lon)

    dLong = end_lon - start_lon

    dPhi = math.log(math.tan(end_lat/2.0+math.pi/4.0)/math.tan(start_lat/2.0+math.pi/4.0))
    if abs(dLong) > math.pi:
        if dLong > 0.0:
            dLong = -(2.0 * math.pi - dLong)
        else:
            dLong = (2.0 * math.pi + dLong)

    y = math.sin(dLong)*math.cos(end_lat)
    x = math.cos(start_lat)*math.sin(end_lat) - math.sin(start_lat)*math.cos(end_lat)*math.cos(dLong)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    return bearing


def interpolate_lat_lon(points, t):
    '''
    Return interpolated lat, lon and compass bearing for time t.

    Points is a list of tuples (time, lat, lon, elevation), t a datetime object.
    '''

    # find the enclosing points in sorted list
    if (t<points[0][0]) or (t>=points[-1][0]):
        raise ValueError("Time t not in scope of gpx file.")

    for i,point in enumerate(points):
        if t<point[0]:
            if i>0:
                before = points[i-1]
            else:
                before = points[i]
            after = points[i]
            break

    # time diff
    dt_before = (t-before[0]).total_seconds()
    dt_after = (after[0]-t).total_seconds()

    # simple linear interpolation
    lat = (before[1]*dt_after + after[1]*dt_before) / (dt_before + dt_after)
    lon = (before[2]*dt_after + after[2]*dt_before) / (dt_before + dt_after)

    bearing = compute_bearing(before[1], before[2], after[1], after[2])

    if before[3] is not None:
        ele = (before[3]*dt_after + after[3]*dt_before) / (dt_before + dt_after)
    else:
        ele = None

    return lat, lon, bearing, ele




def to_deg(value, loc):
    '''
    Convert decimal position to degrees.
    '''
    if value < 0:
        loc_value = loc[0]
    elif value > 0:
        loc_value = loc[1]
    else:
        loc_value = ""
    abs_value = abs(value)
    deg =  int(abs_value)
    t1 = (abs_value-deg)*60
    mint = int(t1)
    sec = round((t1 - mint)* 60, 6)
    return (deg, mint, sec, loc_value)


def add_exif_using_timestamp(filename, points, offset_time=0):
    '''
    Find lat, lon and bearing of filename and write to EXIF.
    '''

    metadata = pyexiv2.ImageMetadata(filename)
    metadata.read()
    t = metadata['Exif.Photo.DateTimeOriginal'].value

    # subtract offset in s beween gpx time and exif time
    t = t - datetime.timedelta(seconds=offset_time)

    try:
        lat, lon, bearing, elevation = interpolate_lat_lon(points, t)

        lat_deg = to_deg(lat, ["S", "N"])
        lon_deg = to_deg(lon, ["W", "E"])

        # convert decimal coordinates into degrees, minutes and seconds as fractions for EXIF
        exiv_lat = (make_fraction(lat_deg[0],1), make_fraction(int(lat_deg[1]),1), make_fraction(int(lat_deg[2]*1000000),1000000))
        exiv_lon = (make_fraction(lon_deg[0],1), make_fraction(int(lon_deg[1]),1), make_fraction(int(lon_deg[2]*1000000),1000000))

        # convert direction into fraction
        exiv_bearing = make_fraction(int(bearing*100),100)

        # add to exif
        metadata["Exif.GPSInfo.GPSLatitude"] = exiv_lat
        metadata["Exif.GPSInfo.GPSLatitudeRef"] = lat_deg[3]
        metadata["Exif.GPSInfo.GPSLongitude"] = exiv_lon
        metadata["Exif.GPSInfo.GPSLongitudeRef"] = lon_deg[3]
        metadata["Exif.Image.GPSTag"] = 654
        metadata["Exif.GPSInfo.GPSMapDatum"] = "WGS-84"
        metadata["Exif.GPSInfo.GPSVersionID"] = '2 0 0 0'
        metadata["Exif.GPSInfo.GPSImgDirection"] = exiv_bearing
        metadata["Exif.GPSInfo.GPSImgDirectionRef"] = "T"
        
        if elevation is not None:
            exiv_elevation = make_fraction(abs(int(elevation*10)),10)
            metadata["Exif.GPSInfo.GPSAltitude"] = exiv_elevation
            metadata["Exif.GPSInfo.GPSAltitudeRef"] = '0' if elevation >= 0 else '1'

        metadata.write()
        print("Added geodata to: {0} ({1}, {2}, {3}), altitude {4}".format(filename, lat, lon, bearing, elevation))
    except ValueError, e:
        print("Skipping {0}: {1}".format(filename, e))




if __name__ == '__main__':
    '''
    Use from command line as: python geotag_from_gpx.py path gpx_file time_offset

    The time_offset is optional and defaults to 0.
    It is defined as 'exif time' - 'gpx time' in whole seconds,
    so if your camera clock is ahead of the gpx clock by 2s,
    then the offset is 2.
    '''

    if len(sys.argv) > 4:
        print("Usage: python geotag_from_gpx.py path gpx_file time_offset")
        raise IOError("Bad input parameters.")
    path = sys.argv[1]
    gpx_filename = sys.argv[2]

    if len(sys.argv) == 4:
        time_offset = int(sys.argv[3])
    else:
        time_offset = 0

    if path.lower().endswith(".jpg"):
        # single file
        file_list = [path]
    else:
        # folder(s)
        file_list = []
        for root, sub_folders, files in os.walk(path):
            file_list += [os.path.join(root, filename) for filename in files if filename.lower().endswith(".jpg")]

    # start time
    t = time.time()

    # read gpx file to get track locations
    gpx = get_lat_lon_time(gpx_filename)

    print("===\nStarting geotagging of {0} images using {1}.\n===".format(len(file_list), gpx_filename))

    for filepath in file_list:
        add_exif_using_timestamp(filepath, gpx, time_offset)

    print("Done geotagging {0} images in {1} seconds.".format(len(file_list), time.time()-t))
