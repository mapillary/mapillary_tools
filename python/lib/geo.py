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
    a2 = WGS84_a**2
    b2 = WGS84_b**2
    lat = math.radians(lat)
    lon = math.radians(lon)
    L = 1.0 / math.sqrt(a2 * math.cos(lat)**2 + b2 * math.sin(lat)**2)
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

    dis = math.sqrt((x1-x2)**2 + (y1-y2)**2 + (z1-z2)**2)

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

def decimal_to_dms(value, loc):
    '''
    Convert decimal position to degrees, minutes, seconds
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

def diff_bearing(b1, b2):
    '''
    Compute difference between two bearings
    '''
    d = abs(b2-b1)
    d = 360-d if d>180 else d
    return d

def offset_bearing(bearing, offset):
    '''
    Add offset to bearing
    '''
    bearing = (bearing + offset + 360) % 360
    return bearing

def normalize_bearing(bearing):
    if bearing > 360:
        # fix negative value wrongly parsed in exifread
        # -360 degree -> 4294966935 when converting from hex
        bearing = bin(int(bearing))[2:]
        bearing = ''.join([str(int(int(a)==0)) for a in bearing])
        bearing = -float(int(bearing, 2))
        bearing %= 360
    bearing = (bearing+360.0)%360
    return bearing

def interpolate_lat_lon(points, t):
    '''
    Return interpolated lat, lon and compass bearing for time t.

    Points is a list of tuples (time, lat, lon, elevation), t a datetime object.
    '''
    # find the enclosing points in sorted list
    if t<points[0][0]:
        raise ValueError("Photo's timestamp is earlier than the earliest time in the GPX file.")
    if t>=points[-1][0]:
        raise ValueError("Photo's timestamp is later than the latest time in the GPX file.")

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
