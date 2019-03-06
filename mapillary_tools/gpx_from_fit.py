from fitparse import FitFile
from geo import semicircle_to_degrees, utc_to_localtime, write_gpx
from tqdm import tqdm

def get_points_from_fit(file_list, local_time=False, verbose=False):
    '''
    Read location and time stamps from a track in a FIT file.

    Returns a list of tuples (time, lat, lon, altitude)
    '''
    data = []
    for file in file_list:
        point = ()
        try:
            fit = FitFile(file)

            messages = fit.get_messages('gps_metadata')
            for record in tqdm(messages, desc='Extracting GPS data from .FIT file'):
                timestamp = record.get('utc_timestamp').value
                timestamp = utc_to_localtime(timestamp) if local_time else timestamp
                lat = semicircle_to_degrees(record.get('position_lat').value)
                lon = semicircle_to_degrees(record.get('position_long').value)
                altitude = record.get('altitude').value
                point = point + (timestamp, lat, lon, altitude)

        except ValueError:
            if verbose:
                print("File {} not formatted properly".format(file))
            pass
        if point:
            data.append(point)
    return data


def gpx_from_fit(file_list, import_path, verbose=False):
    data = get_points_from_fit(file_list)
    data = sorted(data, key=lambda x: x[0])
    gpx_path = import_path + '.gpx'
    write_gpx(gpx_path, data)
    return gpx_path
