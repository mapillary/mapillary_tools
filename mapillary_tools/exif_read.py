#!/usr/bin/env python

import os
import sys
import exifread
import datetime
from geo import normalize_bearing
import uuid
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))
import json


def eval_frac(value):
    if value.den == 0:
        return -1.0
    return float(value.num) / float(value.den)


def format_time(time_string):
    '''
    Format time string with invalid time elements in hours/minutes/seconds
    Format for the timestring needs to be "%Y_%m_%d_%H_%M_%S"

    e.g. 2014_03_31_24_10_11 => 2014_04_01_00_10_11
    '''
    data = time_string.split("_")
    hours, minutes, seconds = int(data[3]), int(data[4]), int(data[5])
    date = datetime.datetime.strptime("_".join(data[:3]), "%Y_%m_%d")
    subsec = 0
    if len(data) == 7:
        subsec = float(data[6]) / 10**len(data[6])
    date_time = date + \
        datetime.timedelta(hours=hours, minutes=minutes,
                           seconds=seconds + subsec)
    return date_time


def gps_to_decimal(values, reference):
    sign = 1 if reference in 'NE' else -1
    degrees = eval_frac(values[0])
    minutes = eval_frac(values[1])
    seconds = eval_frac(values[2])
    return sign * (degrees + minutes / 60 + seconds / 3600)


def exif_datetime_fields():
    '''
    Date time fields in EXIF
    '''
    return [["EXIF DateTimeOriginal",
             "Image DateTimeOriginal",
             "EXIF DateTimeDigitized",
             "Image DateTimeDigitized",
             "EXIF DateTime",
             "Image DateTime",
             "GPS GPSDate",
             "EXIF GPS GPSDate",
             "EXIF DateTimeModified"]]


def exif_gps_date_fields():
    '''
    Date fields in EXIF GPS
    '''
    return [["GPS GPSDate",
             "EXIF GPS GPSDate"]]


class ExifRead:
    '''
    EXIF class for reading exif from an image
    '''

    def __init__(self, filename, details=False):
        '''
        Initialize EXIF object with FILE as filename or fileobj
        '''
        self.filename = filename
        if type(filename) == str:
            with open(filename, 'rb') as fileobj:
                self.tags = exifread.process_file(fileobj, details=details)
        else:
            self.tags = exifread.process_file(filename, details=details)

    def _extract_alternative_fields(self, fields, default=None, field_type=float):
        '''
        Extract a value for a list of ordered fields.
        Return the value of the first existed field in the list
        '''
        for field in fields:
            if field in self.tags:
                if field_type is float:
                    value = eval_frac(self.tags[field].values[0])
                if field_type is str:
                    value = str(self.tags[field].values)
                if field_type is int:
                    value = int(self.tags[field].values[0])
                return value, field
        return default, None

    def exif_name(self):
        '''
        Name of file in the form {lat}_{lon}_{ca}_{datetime}_{filename}_{hash}
        '''
        mapillary_description = json.loads(self.extract_image_description())

        lat = None
        lon = None
        ca = None
        date_time = None

        if "MAPLatitude" in mapillary_description:
            lat = mapillary_description["MAPLatitude"]
        if "MAPLongitude" in mapillary_description:
            lon = mapillary_description["MAPLongitude"]
        if "MAPCompassHeading" in mapillary_description:
            if 'TrueHeading' in mapillary_description["MAPCompassHeading"]:
                ca = mapillary_description["MAPCompassHeading"]['TrueHeading']
        if "MAPCaptureTime" in mapillary_description:
            date_time = datetime.datetime.strptime(
                mapillary_description["MAPCaptureTime"], "%Y_%m_%d_%H_%M_%S_%f").strftime("%Y-%m-%d-%H-%M-%S-%f")[:-3]

        filename = '{}_{}_{}_{}_{}'.format(
            lat, lon, ca, date_time, uuid.uuid4())
        return filename

    def extract_image_history(self):
        field = ['Image Tag 0x9213']
        user_comment, _ = self._extract_alternative_fields(field, '{}', str)
        return user_comment

    def extract_altitude(self):
        '''
        Extract altitude
        '''
        fields = ['GPS GPSAltitude', 'EXIF GPS GPSAltitude']
        altitude, _ = self._extract_alternative_fields(fields, 0, float)
        return altitude

    def extract_capture_time(self):
        '''
        Extract capture time from EXIF
        return a datetime object
        TODO: handle GPS DateTime
        '''
        time_string = exif_datetime_fields()[0]
        capture_time, time_field = self._extract_alternative_fields(
            time_string, 0, str)
        if time_field in exif_gps_date_fields()[0]:
            capture_time = self.extract_gps_time()
            return capture_time

        if capture_time is 0:
            # try interpret the filename
            try:
                capture_time = datetime.datetime.strptime(os.path.basename(
                    self.filename)[:-4] + '000', '%Y_%m_%d_%H_%M_%S_%f')
            except:
                return None
        else:
            capture_time = capture_time.replace(" ", "_")
            capture_time = capture_time.replace(":", "_")
            capture_time = capture_time.replace(".", "_")
            capture_time = capture_time.replace("-", "_")
            capture_time = "_".join(
                [ts for ts in capture_time.split("_") if ts.isdigit()])
            capture_time = format_time(capture_time)
            sub_sec = self.extract_subsec()
            capture_time = capture_time + \
                datetime.timedelta(seconds=float("0." + sub_sec))

        return capture_time

    def extract_direction(self):
        '''
        Extract image direction (i.e. compass, heading, bearing)
        '''
        fields = ['GPS GPSImgDirection',
                  'EXIF GPS GPSImgDirection',
                  'GPS GPSTrack',
                  'EXIF GPS GPSTrack']
        direction, _ = self._extract_alternative_fields(fields)

        if direction is not None:
            direction = normalize_bearing(direction, check_hex=True)
        return direction

    def extract_dop(self):
        '''
        Extract dilution of precision
        '''
        fields = ['GPS GPSDOP', 'EXIF GPS GPSDOP']
        dop, _ = self._extract_alternative_fields(fields)
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

    def extract_gps_time(self):
        '''
        Extract timestamp from GPS field.
        '''
        gps_date_field = "GPS GPSDate"
        gps_time_field = "GPS GPSTimeStamp"
        gps_time = 0
        if gps_date_field in self.tags and gps_time_field in self.tags:
            date = str(self.tags[gps_date_field].values).split(":")
            t = self.tags[gps_time_field]
            gps_time = datetime.datetime(
                year=int(date[0]),
                month=int(date[1]),
                day=int(date[2]),
                hour=int(eval_frac(t.values[0])),
                minute=int(eval_frac(t.values[1])),
                second=int(eval_frac(t.values[2])),
            )
            microseconds = datetime.timedelta(
                microseconds=int((eval_frac(t.values[2]) % 1) * 1e6))
            gps_time += microseconds
        return gps_time

    def extract_exif(self):
        '''
        Extract a list of exif infos
        '''
        width, height = self.extract_image_size()
        make, model = self.extract_make(), self.extract_model()
        orientation = self.extract_orientation()
        geo = self.extract_geo()
        capture = self.extract_capture_time()
        direction = self.extract_direction()
        d = {
            'width': width,
            'height': height,
            'orientation': orientation,
            'direction': direction,
            'make': make,
            'model': model,
            'capture_time': capture
        }
        d['gps'] = geo
        return d

    def extract_image_size(self):
        '''
        Extract image height and width
        '''
        width, _ = self._extract_alternative_fields(
            ['Image ImageWidth', 'EXIF ExifImageWidth'], -1, int)
        height, _ = self._extract_alternative_fields(
            ['Image ImageLength', 'EXIF ExifImageLength'], -1, int)
        return width, height

    def extract_image_description(self):
        '''
        Extract image description
        '''
        description, _ = self._extract_alternative_fields(
            ['Image ImageDescription'], "{}", str)
        return description

    def extract_lon_lat(self):
        if 'GPS GPSLatitude' in self.tags and 'GPS GPSLatitude' in self.tags:
            lat = gps_to_decimal(self.tags['GPS GPSLatitude'].values,
                                 self.tags['GPS GPSLatitudeRef'].values)
            lon = gps_to_decimal(self.tags['GPS GPSLongitude'].values,
                                 self.tags['GPS GPSLongitudeRef'].values)
        elif 'EXIF GPS GPSLatitude' in self.tags and 'EXIF GPS GPSLatitude' in self.tags:
            lat = gps_to_decimal(self.tags['EXIF GPS GPSLatitude'].values,
                                 self.tags['EXIF GPS GPSLatitudeRef'].values)
            lon = gps_to_decimal(self.tags['EXIF GPS GPSLongitude'].values,
                                 self.tags['EXIF GPS GPSLongitudeRef'].values)
        else:
            lon, lat = None, None
        return lon, lat

    def extract_make(self):
        '''
        Extract camera make
        '''
        fields = ['EXIF LensMake', 'Image Make']
        make, _ = self._extract_alternative_fields(
            fields, default='none', field_type=str)
        return make

    def extract_model(self):
        '''
        Extract camera model
        '''
        fields = ['EXIF LensModel', 'Image Model']
        model, _ = self._extract_alternative_fields(
            fields, default='none', field_type=str)
        return model

    def extract_orientation(self):
        '''
        Extract image orientation
        '''
        fields = ['Image Orientation']
        orientation, _ = self._extract_alternative_fields(
            fields, default=1, field_type=int)
        if orientation not in range(1, 9):
            return 1
        return orientation

    def extract_subsec(self):
        '''
        Extract microseconds
        '''
        fields = [
            'Image SubSecTimeOriginal',
            'EXIF SubSecTimeOriginal',
            'Image SubSecTimeDigitized',
            'EXIF SubSecTimeDigitized',
            'Image SubSecTime',
            'EXIF SubSecTime'
        ]
        sub_sec, _ = self._extract_alternative_fields(
            fields, default='', field_type=str)
        return sub_sec

    def fields_exist(self, fields):
        '''
        Check existence of a list fields in exif
        '''
        for rexif in fields:
            vflag = False
            for subrexif in rexif:
                if subrexif in self.tags:
                    vflag = True
            if not vflag:
                print("Missing required EXIF tag: {0} for image {1}".format(
                    rexif[0], self.filename))
                return False
        return True

    def mapillary_tag_exists(self):
        '''
        Check existence of required Mapillary tags
        '''
        description_tag = "Image ImageDescription"
        if description_tag not in self.tags:
            return False
        for requirement in ["MAPSequenceUUID", "MAPSettingsUserKey", "MAPCaptureTime", "MAPLongitude", "MAPLatitude"]:
            if requirement not in self.tags[description_tag].values or json.loads(self.tags[description_tag].values)[requirement] in ["", None, " "]:
                return False
        return True
