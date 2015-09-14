# -*- coding: utf-8 -*-

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
