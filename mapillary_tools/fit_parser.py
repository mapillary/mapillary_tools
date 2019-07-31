#!/usr/bin/env python

from fitparse import FitFile
import datetime
from tqdm import tqdm

'''
Methods for parsing gps data from Garmin FIT files
'''


def parse_uuid_string(uuid_string):
    '''
    Parses a video uuid string from fit similar to:  VIRBactioncameraULTRA30_Timelapse_3840_2160_1.0000_3936073999_36a2eff0_1_111_2019-01-17-09-01-03.fit
    Returns a tuple (camera_type, video_type, width, height, frame_rate, serial, unknown_1, unkown_2, video_id, fit_filename)
    '''
    return tuple(uuid_string.split("_"))


def get_lat_lon_time_from_fit(geotag_file_list, local_time=True, verbose=False):
    '''
    Read location and time stamps from a track in a FIT file.

    Returns a tuple (video_start_time, points) where points is a list of tuples (time, lat, lon, altitude)
    '''
    vids = {}
    for geotag_file in geotag_file_list:

        alt = None
        lat = None
        lon = None
        time_delta = None
        try:
            fit = FitFile(geotag_file)

            vid_times = {}

            timestamp_correlations = fit.get_messages(162)
            timestamp_correlation = next(timestamp_correlations).get_values()
            timestamp = timestamp_correlation['local_timestamp']
            offset = datetime.timedelta(seconds=timestamp_correlation['system_timestamp'],
                                         milliseconds=timestamp_correlation['system_timestamp_ms'])
            start_time = timestamp - offset
            camera_events = (c for c in fit.get_messages(161) if c.get('camera_event_type').value in ['video_second_stream_start', 'video_second_stream_end'])
            for start in tqdm(camera_events, desc='Extracting Video data from .FIT file'):
                vid_id = parse_uuid_string(start.get('camera_file_uuid').value)[-2]
                end = next(camera_events)
                start_timedelta = datetime.timedelta(seconds=start.get('timestamp').value, milliseconds=start.get('timestamp_ms').value)
                start_timestamp = start_time + start_timedelta
                end_timedelta = datetime.timedelta(seconds=end.get('timestamp').value, milliseconds=end.get('timestamp_ms').value)
                end_timestamp = start_time + end_timedelta
                vid_times[vid_id] = (start_timestamp, end_timestamp)

            points = []
            for vid_id, times in tqdm(vid_times.items(), desc='Extracting GPS data from .FIT file'):
                gps_metadata = (g for g in fit.get_messages(160) if times[0] <= (start_time + datetime.timedelta(seconds=g.get('timestamp').value, milliseconds=g.get('timestamp_ms').value)) <= times[-1])
                for gps in gps_metadata:
                    try:
                        alt = gps.get('enhanced_altitude').value
                        lat_in_semicircles = gps.get('position_lat').value
                        lat = float(lat_in_semicircles) * 180 / 2**31
                        lon_in_semicircles = gps.get('position_long').value
                        lon = float(lon_in_semicircles) * 180 / 2**31
                        time_delta = datetime.timedelta(seconds=gps.get('timestamp').value, milliseconds=gps.get('timestamp_ms').value)
                        wp_datetime = start_time + time_delta
                    except:
                        continue
                    if alt is not None and lat is not None and lon is not None and wp_datetime is not None and times[0] <= wp_datetime <= times[-1]:
                        points.append((wp_datetime, lat, lon, alt))
                try:
                    vids[int(vid_id)] = (times[0], sorted(points))
                except:
                    vids[vid_id] = (times[0], sorted(points))

        except ValueError:
            if verbose:
                print("Warning: {} is not formatted properly".format(geotag_file))
            pass
        except StopIteration:
            if verbose:
                print("Warning: {} does not have enough iterations".format(geotag_file))
            pass
    return vids
