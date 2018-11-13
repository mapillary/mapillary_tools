# -*- coding: utf-8 -*-

import datetime
import math
WGS84_a = 6378137.0
WGS84_b = 6356752.314245


def ecef_from_lla(lat, lon, alt):
    '''
    Compute ECEF XYZ from latitude, longitude and altitude.

    All using the WGS94 model.
    Altitude is the distance to the WGS94 ellipsoid.
    Check results here http://www.oc.nps.edu/oc2902w/coord/llhxyz.htm

    '''
    a2 = WGS84_a ** 2
    b2 = WGS84_b ** 2
    lat = math.radians(lat)
    lon = math.radians(lon)
    L = 1.0 / math.sqrt(a2 * math.cos(lat) ** 2 + b2 * math.sin(lat) ** 2)
    x = (a2 * L + alt) * math.cos(lat) * math.cos(lon)
    y = (a2 * L + alt) * math.cos(lat) * math.sin(lon)
    z = (b2 * L + alt) * math.sin(lat)
    return x, y, z


def gps_distance(latlon_1, latlon_2):
    '''
    Distance between two (lat,lon) pairs.

    >>> p1 = (42.1, -11.1)
    >>> p2 = (42.2, -11.3)
    >>> 19000 < gps_distance(p1, p2) < 20000
    True
    '''
    x1, y1, z1 = ecef_from_lla(latlon_1[0], latlon_1[1], 0.)
    x2, y2, z2 = ecef_from_lla(latlon_2[0], latlon_2[1], 0.)

    dis = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)

    return dis


def dms_to_decimal(degrees, minutes, seconds, hemisphere):
    '''
    Convert from degrees, minutes, seconds to decimal degrees.
    @author: mprins
    '''
    dms = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    if hemisphere in "WwSs":
        dms = -1 * dms

    return dms


def decimal_to_dms(value, precision):
    '''
    Convert decimal position to degrees, minutes, seconds in a fromat supported by EXIF
    '''
    deg = math.floor(value)
    min = math.floor((value - deg) * 60)
    sec = math.floor((value - deg - min / 60) * 3600 * precision)

    return ((deg, 1), (min, 1), (sec, precision))


def gpgga_to_dms(gpgga):
    '''
    Convert GPS coordinate in GPGGA format to degree/minute/second

    Reference: http://us.cactii.net/~bb/gps.py
    '''
    deg_min, dmin = gpgga.split('.')
    degrees = int(deg_min[:-2])
    minutes = float('%s.%s' % (deg_min[-2:], dmin))
    decimal = degrees + (minutes / 60)
    return decimal


def utc_to_localtime(utc_time):
    utc_offset_timedelta = datetime.datetime.utcnow() - datetime.datetime.now()
    return utc_time - utc_offset_timedelta


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

    dPhi = math.log(math.tan(end_lat / 2.0 + math.pi / 4.0) /
                    math.tan(start_lat / 2.0 + math.pi / 4.0))
    if abs(dLong) > math.pi:
        if dLong > 0.0:
            dLong = -(2.0 * math.pi - dLong)
        else:
            dLong = (2.0 * math.pi + dLong)

    y = math.sin(dLong) * math.cos(end_lat)
    x = math.cos(start_lat) * math.sin(end_lat) - \
        math.sin(start_lat) * math.cos(end_lat) * math.cos(dLong)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    return bearing


def diff_bearing(b1, b2):
    '''
    Compute difference between two bearings
    '''
    d = abs(b2 - b1)
    d = 360 - d if d > 180 else d
    return d


def offset_bearing(bearing, offset):
    '''
    Add offset to bearing
    '''
    bearing = (bearing + offset) % 360
    return bearing


def normalize_bearing(bearing, check_hex=False):
    '''
    Normalize bearing and convert from hex if
    '''
    if bearing > 360 and check_hex:
        # fix negative value wrongly parsed in exifread
        # -360 degree -> 4294966935 when converting from hex
        bearing = bin(int(bearing))[2:]
        bearing = ''.join([str(int(int(a) == 0)) for a in bearing])
        bearing = -float(int(bearing, 2))
    bearing %= 360
    return bearing


def interpolate_lat_lon(points, t, max_dt=1):
    '''
    Return interpolated lat, lon and compass bearing for time t.

    Points is a list of tuples (time, lat, lon, elevation), t a datetime object.
    '''
    # find the enclosing points in sorted list
    if (t <= points[0][0]) or (t >= points[-1][0]):
        if t <= points[0][0]:
            dt = abs((points[0][0] - t).total_seconds())
        else:
            dt = (t - points[-1][0]).total_seconds()
        if dt > max_dt:
            raise ValueError(
                "time t not in scope of gpx file by {} seconds".format(dt))
        else:
            print(
                "time t not in scope of gpx file by {} seconds, extrapolating...".format(dt))

        if t < points[0][0]:
            before = points[0]
            after = points[1]
        else:
            before = points[-2]
            after = points[-1]
        bearing = compute_bearing(before[1], before[2], after[1], after[2])

        if t == points[0][0]:
            x = points[0]
            return (x[1], x[2], bearing, x[3])

        if t == points[-1][0]:
            x = points[-1]
            return (x[1], x[2], bearing, x[3])
    else:
        for i, point in enumerate(points):
            if t < point[0]:
                if i > 0:
                    before = points[i - 1]
                else:
                    before = points[i]
                after = points[i]
                break

    # weight based on time
    weight = (t - before[0]).total_seconds() / \
        (after[0] - before[0]).total_seconds()

    # simple linear interpolation in case points are not the same
    if before[1] == after[1]:
        lat = before[1]
    else:
        lat = before[1] - weight * before[1] + weight * after[1]

    if before[2] == after[2]:
        lon = before[2]
    else:
        lon = before[2] - weight * before[2] + weight * after[2]

    # camera angle
    bearing = compute_bearing(before[1], before[2], after[1], after[2])

    # altitude
    if before[3] is not None:
        ele = before[3] - weight * before[3] + weight * after[3]
    else:
        ele = None

    return lat, lon, bearing, ele


def write_gpx(filename, gps_trace):
    time_format = "%Y-%m-%dT%H:%M:%S.%f"
    gpx = "<gpx>" + "\n"
    gpx += "<trk>" + "\n"
    gpx += "<name>Mapillary GPX</name>" + "\n"
    gpx += "<trkseg>" + "\n"
    for point in gps_trace:
        lat = point[1]
        lon = point[2]
        time = datetime.datetime.strftime(point[0], time_format)[:-3]
        elevation = point[3]
        gpx += "<trkpt lat=\"" + \
            str(lat) + "\" lon=\"" + str(lon) + "\">" + "\n"
        gpx += "<ele>" + str(elevation) + "</ele>" + "\n"
        gpx += "<time>" + time + "</time>" + "\n"
        gpx += "</trkpt>" + "\n"
    gpx += "</trkseg>" + "\n"
    gpx += "</trk>" + "\n"
    gpx += "</gpx>" + "\n"
    with open(filename, "w") as fout:
        fout.write(gpx)
