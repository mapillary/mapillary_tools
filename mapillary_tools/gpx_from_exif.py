from . import exif_read
from .geo import write_gpx


def get_points_from_exif(file_list, verbose=False):
    data = []
    for file in file_list:
        point = ()
        try:
            exif = exif_read.ExifRead(file)
        except:
            if verbose:
                print(f"Warning, EXIF could not be read for image {file}.")
            continue
        try:
            lon, lat = exif.extract_lon_lat()
        except:
            if verbose:
                print(f"Warning {file} image latitude or longitude tag not in EXIF.")
            continue
        try:
            timestamp = exif.extract_capture_time()
        except:
            if verbose:
                print(f"Warning {file} image capture time tag not in EXIF.")
            continue
        if lon is not None and lat is not None and timestamp is not None:
            point = point + (timestamp, lat, lon)
        else:
            continue
        try:
            altitude = exif.extract_altitude()
            point = point + (altitude,)
        except:
            pass
        try:
            heading = exif.extract_direction()
            point = point + (heading,)
        except:
            pass
        if point:
            data.append(point)
    return data


def gpx_from_exif(file_list, import_path, verbose=False):
    data = get_points_from_exif(file_list, verbose)
    data = sorted(data, key=lambda x: x[0])
    gpx_path = import_path + ".gpx"
    write_gpx(gpx_path, data)
    return gpx_path
