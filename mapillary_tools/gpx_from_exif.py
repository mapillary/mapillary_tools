import gpxpy
import exif_read


def write_gpx(path, data):
    gpx = gpxpy.gpx.GPX()
    gpx_track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(gpx_track)
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(gpx_segment)
    for point in data:
        gpx_segment.points.append(gpxpy.gpx.GPXTrackPoint(
            point[1], point[2], elevation=point[3], time=point[0]))
    with open(path, "w") as f:
        f.write(gpx.to_xml())


def get_points_from_exif(file_list, verbose=False):
    data = []
    for file in file_list:
        point = ()
        try:
            exif = exif_read.ExifRead(file)
        except:
            if verbose:
                print("Warning, EXIF could not be read for image {}.".format(file))
            continue
        try:
            lon, lat = exif.extract_lon_lat()
        except:
            if verbose:
                print(
                    "Warning {} image latitude or longitude tag not in EXIF.".format(file))
            continue
        try:
            timestamp = exif.extract_capture_time()
        except:
            if verbose:
                print(
                    "Warning {} image capture time tag not in EXIF.".format(file))
            continue
        if lon != None and lat != None and timestamp != None:
            point = point + (timestamp, lat, lon)
        else:
            continue
        try:
            altitude = exif.extract_altitude()
            point = point + (altitude, )
        except:
            pass
        try:
            heading = exif.extract_direction()
            point = point + (heading, )
        except:
            pass
        if point:
            data.append(point)
    return data


def gpx_from_exif(file_list, import_path, verbose=False):
    data = get_points_from_exif(file_list, verbose)
    gpx_path = import_path + '.gpx'
    write_gpx(gpx_path, data)
    return gpx_path
