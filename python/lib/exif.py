#!/usr/bin/env python
import os.path, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import exifread
import datetime

def eval_frac(value):
    return float(value.num) / float(value.den)

def gps_to_decimal(values, reference):
    sign = 1 if reference in 'NE' else -1
    degrees = eval_frac(values[0])
    minutes = eval_frac(values[1])
    seconds = eval_frac(values[2])
    return sign * (degrees + minutes / 60 + seconds / 3600)

def get_float_tag(tags, key):
    if key in tags:
        return float(tags[key].values[0])
    else:
        return None

def get_frac_tag(tags, key):
    if key in tags:
        return eval_frac(tags[key].values[0])
    else:
        return None

def extract_exif_from_file(fileobj):
    if isinstance(fileobj, (str, unicode)):
        with open(fileobj) as f:
            exif_data = EXIF(f)
    else:
        exif_data = EXIF(fileobj)

    d = exif_data.extract_exif()
    return d

class EXIF:
    '''
    EXIF class for reading exif from an image
    '''
    def __init__(self, FILE):
        '''
        Initialize EXIF object with FILE as filename or fileobj
        '''
        if type(FILE)==str:
            with open(FILE, 'rb') as fileobj:
                self.tags = exifread.process_file(fileobj, details=False)
        else:
            self.tags = exifread.process_file(FILE, details=False)

    def extract_image_size(self):
        '''
        Extract image height and width
        '''
        if 'Image ImageWidth' in self.tags and 'Image ImageLength' in self.tags:
            width, height = (int(self.tags['Image ImageWidth'].values[0]),
                            int(self.tags['Image ImageLength'].values[0]) )
        else:
            width, height = -1, -1
        return width, height

    def extract_make(self):
        '''
        Extract camera make
        '''
        if 'EXIF LensMake' in self.tags:
            make = self.tags['EXIF LensMake'].values
        elif 'Image Make' in self.tags:
            make = self.tags['Image Make'].values
        else:
            make = 'unknown'
        return make

    def extract_model(self):
        '''
        Extract camera model
        '''
        if 'EXIF LensModel' in self.tags:
            model = self.tags['EXIF LensModel'].values
        elif 'Image Model' in self.tags:
            model = self.tags['Image Model'].values
        else:
            model = 'unknown'
        return model

    def extract_orientation(self):
        if 'Image Orientation' in self.tags:
            orientation = self.tags.get('Image Orientation').values[0]
        else:
            orientation = 1
        return orientation

    def extract_lon_lat(self):
        if 'GPS GPSLatitude' in self.tags:
            lat = gps_to_decimal(self.tags['GPS GPSLatitude'].values,
                                 self.tags['GPS GPSLatitudeRef'].values)
            lon = gps_to_decimal(self.tags['GPS GPSLongitude'].values,
                                 self.tags['GPS GPSLongitudeRef'].values)
        else:
            lon, lat = None, None
        return lon, lat

    def extract_altitude(self):
        if 'GPS GPSAltitude' in self.tags:
            altitude = eval_frac(self.tags['GPS GPSAltitude'].values[0])
        else:
            altitude = None
        return altitude

    def extract_dop(self):
        if 'GPS GPSDOP' in self.tags:
            dop = eval_frac(self.tags['GPS GPSDOP'].values[0])
        else:
            dop = None
        return dop

    def extract_geo(self):
        '''
        Extract geo-related information from exif
        '''
        altitude = self.extract_altitude()
        dop = self.extract_dop()
        lon, lat = self.extract_lon_lat()
        d = {}

        if lon is not None and lat is not None:
            d['latitude'] = lat
            d['longitude'] = lon
        if altitude is not None:
            d['altitude'] = altitude
        if dop is not None:
            d['dop'] = dop
        return d

    def extract_capture_time(self):
        '''
        Extract capture time from EXIF
        '''
        time_string = ["EXIF DateTimeOriginal",
                       "EXIF DateTimeDigitized",
                       "Image DateTimeOriginal",
                       "Image DateTimeDigitized",
                       "Image DateTime"]

        capture_time = 0
        for ts in time_string:
          if capture_time == 0:
            if ts in self.tags:
                capture_time = str(self.tags.get(ts).values)
                capture_time = capture_time.replace(" ","_")
                capture_time = capture_time.replace(":","_")
                capture_time = datetime.datetime.strptime(capture_time, '%Y_%m_%d_%H_%M_%S')
        return capture_time

    def extract_exif(self):
        '''
        Extract a list of exif infos
        '''
        width, height = self.extract_image_size()
        make, model = self.extract_make(), self.extract_model()
        orientation = self.extract_orientation()
        geo = self.extract_geo()
        capture = self.extract_capture_time()
        d = {
                'width': width,
                'height': height,
                'orientation': orientation,
                'make': make,
                'model': model,
                'capture_time': capture
            }
        d['gps'] = geo
        return d