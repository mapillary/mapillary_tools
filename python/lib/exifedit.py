import sys
import json
import datetime
import hashlib
import base64
import uuid
import pyexiv2
from pyexiv2.utils import make_fraction
from lib.geo import decimal_to_dms, normalize_bearing
from lib.exif import EXIF, verify_exif

def create_mapillary_description(filename, username, email,
                                 upload_hash, sequence_uuid,
                                 interpolated_heading=None,
                                 orientation=1,
                                 verbose=False):
    '''
    Check that image file has the required EXIF fields.

    Incompatible files will be ignored server side.
    '''
    # read exif
    exif = EXIF(filename)

    if not verify_exif(filename):
        return False

    # write the mapillary tag
    mapillary_description = {}
    mapillary_description["MAPLongitude"], mapillary_description["MAPLatitude"] = exif.extract_lon_lat()
    #required date format: 2015_01_14_09_37_01_000
    mapillary_description["MAPCaptureTime"] = datetime.datetime.strftime(exif.extract_capture_time(), "%Y_%m_%d_%H_%M_%S_%f")[:-3]
    mapillary_description["MAPOrientation"] = exif.extract_orientation()
    heading = exif.extract_direction()
    if heading is None:
        heading = 0.0
    heading = normalize_bearing(interpolated_heading) if interpolated_heading is not None else normalize_bearing(heading)
    mapillary_description["MAPCompassHeading"] = {"TrueHeading": heading, "MagneticHeading": heading}
    mapillary_description["MAPSettingsUploadHash"] = upload_hash
    mapillary_description["MAPSettingsEmail"] = email
    mapillary_description["MAPSettingsUsername"] = username
    settings_upload_hash = hashlib.sha256("%s%s%s" % (upload_hash, email, base64.b64encode(filename))).hexdigest()
    mapillary_description['MAPSettingsUploadHash'] = settings_upload_hash
    mapillary_description['MAPPhotoUUID'] = str(uuid.uuid4())
    mapillary_description['MAPSequenceUUID'] = str(sequence_uuid)
    mapillary_description['MAPDeviceModel'] = exif.extract_model()
    mapillary_description['MAPDeviceMake'] = exif.extract_make()

    # write to file
    json_desc = json.dumps(mapillary_description)
    if verbose:
        print "tag: {0}".format(json_desc)
    metadata = ExifEdit(filename)
    metadata.add_image_description(json_desc)
    metadata.add_orientation(orientation)
    metadata.add_direction(heading)
    metadata.write()


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