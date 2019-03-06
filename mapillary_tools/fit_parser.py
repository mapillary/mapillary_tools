#!/usr/bin/env python

from fitparse import FitFile
from tqdm import tqdm
from geo import utc_to_localtime, semicircle_to_degrees

'''
Methods for parsing gps data from Garmin FIT files
'''

def get_lat_lon_time_from_fit(file_list, local_time=True, verbose=False):
    '''
    Read location and time stamps from a track in a FIT file.

    Returns a list of tuples (time, lat, lon, altitude)
    '''
    points = []
    for file in file_list:
        try:
            fit = FitFile(file)

            messages = fit.get_messages('gps_metadata')
            for record in tqdm(messages, desc='Extracting GPS data from .FIT file'):
                timestamp = record.get('utc_timestamp').value
                timestamp = utc_to_localtime(timestamp) if local_time else timestamp
                lat = semicircle_to_degrees(record.get('position_lat').value)
                lon = semicircle_to_degrees(record.get('position_long').value)
                try:
                    altitude = record.get('altitude').value
                except AttributeError:
                    altitude = record.get('enhanced_altitude').value
                points.append((timestamp, lat, lon, altitude))

        except ValueError:
            if verbose:
                print("File {} not formatted properly".format(file))
            pass
    points.sort()
    return points
