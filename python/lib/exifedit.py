import sys
import json
import pyexiv2
from pyexiv2.utils import make_fraction
from lib.geo import decimal_to_dms

'''
A class for edit EXIF using pyexiv2
'''

class ExifEdit(object):

    def __init__(self, filename, precision=1000):
        self.filename = filename
        self.metadata = pyexiv2.ImageMetadata(filename)
        self.metadata.read()
        self.precision = 1000

    def add_image_description(self, description):
        ''' Add a dict to image description
        @params description: string
        '''
        self.metadata['Exif.Image.ImageDescription'] = description

    def add_orientation(self, orientation):
        ''' Add image orientation
        '''
        self.metadata['Exif.Image.Orientation'] = int(orientation)

    def add_date_time_original(self, date_time):
        ''' Add date time original
        @params date_time: datetime object
        '''
        date_format='%Y:%m:%d %H:%M:%S'
        self.metadata['Exif.Photo.DateTimeOriginal'] = date_time.strftime(date_format)

    def add_lat_lon(self, lat, lon, precision=1000000):
        ''' Add lat, lon to gps (lat, lon in float)
        @source: originally from geotag_from_gpx.py
        '''

        # convert decimal coordinates into degrees, minutes and seconds
        lat_deg = decimal_to_dms(lat, ["S", "N"])
        lon_deg = decimal_to_dms(lon, ["W", "E"])

        # convert degrees, minutes and seconds as fractions for EXIF
        exiv_lat = (make_fraction(lat_deg[0],1), make_fraction(int(lat_deg[1]),1), make_fraction(int(lat_deg[2]*precision),precision))
        exiv_lon = (make_fraction(lon_deg[0],1), make_fraction(int(lon_deg[1]),1), make_fraction(int(lon_deg[2]*precision),precision))

        # add to exif
        self.metadata["Exif.GPSInfo.GPSLatitude"] = exiv_lat
        self.metadata["Exif.GPSInfo.GPSLatitudeRef"] = lat_deg[3]
        self.metadata["Exif.GPSInfo.GPSLongitude"] = exiv_lon
        self.metadata["Exif.GPSInfo.GPSLongitudeRef"] = lon_deg[3]
        self.metadata["Exif.Image.GPSTag"] = 654
        self.metadata["Exif.GPSInfo.GPSMapDatum"] = "WGS-84"
        self.metadata["Exif.GPSInfo.GPSVersionID"] = '2 0 0 0'

    def add_dop(self, dop, precision=100):
        ''' Add GPSDOP (float)
        '''
        self.metadata['Exif.GPSInfo.GPSDOP'] = self.make_fraction(dop, precision)

    def add_altitude(self, altitude, precision=100):
        ''' Add altitude (precision is the precision)
        '''
        self.metadata['Exif.GPSInfo.GPSAltitude'] = self.make_fraction(altitude, precision)
        self.metadata['Exif.GPSInfo.GPSAltitudeRef'] = '0' if altitude >= 0 else '1'

    def add_direction(self, direction, ref="T", precision=10):
        ''' Add image direction
        '''
        if direction < 0:
            direction += 360.
        exiv_direction = self.make_fraction(direction, precision)
        self.metadata["Exif.GPSInfo.GPSImgDirection"] = exiv_direction
        self.metadata["Exif.GPSInfo.GPSImgDirectionRef"] = "T"

    def make_fraction(self, v, precision=1000):
        ''' Make fraction with the specified precision
        '''
        fv = make_fraction(int(v * precision), precision)
        return fv

    def write(self, filename=None):
        self.metadata.write()