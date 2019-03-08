#!/usr/bin/env python

from fitparse import FitFile
import datetime
import os
from tqdm import tqdm

'''
Methods for parsing gps data from Garmin FIT files
'''


def get_lat_lon_time_from_fit(geotag_file_list, local_time=True, verbose=False):
    '''
    Read location and time stamps from a track in a FIT file.

    Returns a list of tuples (time, lat, lon, altitude)
    '''
    points = []
    for geotag_file in geotag_file_list:
        basename = os.path.basename(geotag_file)
        basename_no_extension = os.path.splitext(basename)[0]

        alt = None
        lat = None
        lon = None
        time_delta = None
        start_time = datetime.datetime.strptime(basename_no_extension, "%Y-%m-%d-%H-%M-%S") + datetime.timedelta(seconds=27)
        try:
            fit = FitFile(geotag_file)

            messages = fit.get_messages(20)
            for record in tqdm(messages, desc='Extracting GPS data from .FIT file'):
                try:
                    alt = record.get('enhanced_altitude').value
                    lat_in_semicircles = record.get('position_lat').value
                    lat = float(lat_in_semicircles) * 180 / 2**31 
                    lon_in_semicircles = record.get('position_long').value
                    lon = float(lon_in_semicircles) * 180 / 2**31 
                    time_delta = datetime.timedelta(seconds=record.get('timestamp').value)
                    wp_datetime = start_time + time_delta
                except AttributeError:
                    continue
                if alt is not None and lat is not None and lon is not None and time_delta is not None:
                    points.append((wp_datetime,lat,lon,alt))

        except ValueError:
            if verbose:
                print("File {} not formatted properly".format(geotag_file))
            pass
    points.sort()
    return points
