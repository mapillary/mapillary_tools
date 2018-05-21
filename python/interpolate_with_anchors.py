#!/usr/bin/env python

import datetime
from lib.geo import interpolate_lat_lon, compute_bearing, offset_bearing
from lib.sequence import Sequence
import lib.io
import os
import sys
from lib.exifedit import ExifEdit

def interpolate_with_anchors(anchors, angle_offset):
    '''
    Interpolate gps position and compass angle given a list of anchors
        anchor:
            lat: latitude
            lon: longitude
            alt: altitude
            datetime: date time of the anchor (datetime object)
            num_image: number of images in between two anchors
    '''
    points = [ (a['datetime'], a['lat'], a['lon'], a.get('alt', 0)) for a in anchors]

    inter_points = []
    for i, (a1, a2) in enumerate(zip(points[:], points[1:])):
        t1 = a1[0]
        t2 = a2[0]
        num_image = anchors[i]['num_image']
        delta = (t2-t1).total_seconds()/float(num_image+1)
        inter_points.append(points[i]+(0.0,))
        for ii in xrange(num_image):
            t = t1 + datetime.timedelta(seconds=(ii+1)*delta)
            p = interpolate_lat_lon(points, t)
            inter_points.append((t,)+p)
    inter_points.append(points[-1]+(0,0,))

    # get angles
    bearings = [offset_bearing(compute_bearing(ll1[1], ll1[2], ll2[1], ll2[2]), angle_offset)
                    for ll1, ll2 in zip(inter_points, inter_points[1:])]
    bearings.append(bearings[-1])
    inter_points = [ (p[0], p[1], p[2], p[4], bearing) for p, bearing in zip(inter_points, bearings)]

    return inter_points

def point(lat, lon, alt, datetime, num_image):
    return {
                'lat': lat,
                'lon': lon,
                'alt': alt,
                'datetime': datetime,
                'num_image': num_image
           }

def test_run(image_path):
    '''
    Test run for images
    '''
    s = Sequence(image_path, check_exif=False)
    file_list = s.get_file_list(image_path)
    num_image = len(file_list)

    t1 = datetime.datetime.strptime('2000_09_03_12_00_00', '%Y_%m_%d_%H_%M_%S')
    t2 = datetime.datetime.strptime('2000_09_03_12_30_00', '%Y_%m_%d_%H_%M_%S')

    p1 = point(0.5, 0.5, 0.2, t1, num_image-2)
    p2 = point(0.55, 0.55, 0.0, t2, 0)

    inter_points = interpolate_with_anchors([p1, p2], angle_offset=-90.0)

    save_path = os.path.join(image_path, 'processed')
    lib.io.mkdir_p(save_path)

    assert(len(inter_points)==len(file_list))

    for f, p in zip(file_list, inter_points):
        meta = ExifEdit(f)
        meta.add_lat_lon(p[1], p[2])
        meta.add_altitude(p[3])
        meta.add_date_time_original(p[0])
        meta.add_orientation(1)
        meta.add_direction(p[4])
        meta.write()

