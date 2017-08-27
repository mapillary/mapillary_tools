import sys
import json
import datetime
import hashlib
import base64
import uuid
from lib.geo import normalize_bearing
from lib.exif import EXIF, verify_exif
from lib.pexif import JpegFile, Rational
import shutil

def create_mapillary_description(filename, username, email, userkey,
                                 upload_hash, sequence_uuid,
                                 interpolated_heading=None,
                                 offset_angle=0.0,
                                 timestamp=None,
                                 orientation=None,
                                 project="",
                                 secret_hash=None,
                                 external_properties=None,
                                 verbose=False):
    '''
    Check that image file has the required EXIF fields.

    Incompatible files will be ignored server side.
    '''
    # read exif
    exif = EXIF(filename)

    if not verify_exif(filename):
        return False

    if orientation is None:
        orientation = exif.extract_orientation()

    # write the mapillary tag
    mapillary_description = {}

    # lat, lon of the image, takes precedence over EXIF GPS values
    mapillary_description["MAPLongitude"], mapillary_description["MAPLatitude"] = exif.extract_lon_lat()

    # altitude of the image, takes precedence over EXIF GPS values, assumed 0 if missing
    mapillary_description["MAPAltitude"] = exif.extract_altitude()

    # capture time: required date format: 2015_01_14_09_37_01_000, TZ MUST be UTC
    if timestamp is None:
        timestamp = exif.extract_capture_time()

    #  The capture time of the image in UTC. Will take precedence over any other time tags in the EXIF
    mapillary_description["MAPCaptureTime"] = datetime.datetime.strftime(timestamp, "%Y_%m_%d_%H_%M_%S_%f")[:-3]

    # EXIF orientation of the image
    mapillary_description["MAPOrientation"] = orientation
    heading = exif.extract_direction()

    if heading is None:
        heading = 0.0
    heading = normalize_bearing(interpolated_heading + offset_angle) if interpolated_heading is not None else normalize_bearing(heading + offset_angle)

    # bearing of the image
    mapillary_description["MAPCompassHeading"] = {"TrueHeading": heading, "MagneticHeading": heading}

    # authentication
    assert(email is not None or userkey is not None)
    if email is not None:
        mapillary_description["MAPSettingsEmail"] = email
    if username is not None:
        mapillary_description["MAPSettingsUsername"] = username

    # use this if available, and omit MAPSettingsUsername and MAPSettingsEmail for privacy reasons
    if userkey is not None:
        mapillary_description["MAPSettingsUserKey"] = userkey
    if upload_hash is not None:
        settings_upload_hash = hashlib.sha256("%s%s%s" % (upload_hash, email, base64.b64encode(filename))).hexdigest()
        # this is not checked in the backend right now, will likely be changed to have user_key instead of email as part
        # of the hash
        mapillary_description['MAPSettingsUploadHash'] = settings_upload_hash

    # a unique photo ID to check for duplicates in the backend in case the image gets uploaded more than once
    mapillary_description['MAPPhotoUUID'] = str(uuid.uuid4())
    # a sequene ID to make the images go together (order by MAPCaptureTime)
    mapillary_description['MAPSequenceUUID'] = str(sequence_uuid)

    # The device model
    mapillary_description['MAPDeviceModel'] = exif.extract_model()

    # The device manufacturer
    mapillary_description['MAPDeviceMake'] = exif.extract_make()
    if upload_hash is None and secret_hash is not None:
        mapillary_description['MAPVideoSecure'] = secret_hash

    mapillary_description["MAPSettingsProject"] = project

    # external properties (optional)
    if external_properties is not None:
        # externl proerties can be saved and searched in Mapillary later on
        mapillary_description['MAPExternalProperties'] = external_properties

    # write to file
    if verbose:
        print("tag: {0}".format(mapillary_description))
    metadata = ExifEdit(filename)
    metadata.add_image_description(mapillary_description)
    metadata.add_orientation(orientation)
    metadata.add_direction(heading)
    metadata.write()

def add_mapillary_description(filename, username, email,
                              project, upload_hash, image_description,
                              output_file=None):
    """Add Mapillary description tags directly with user info."""

    if username is not None:
        # write the mapillary tag
        image_description["MAPSettingsUploadHash"] = upload_hash
        image_description["MAPSettingsEmail"] = email
        image_description["MAPSettingsUsername"] = username
        settings_upload_hash = hashlib.sha256("%s%s%s" % (upload_hash, email, base64.b64encode(filename))).hexdigest()

        image_description['MAPSettingsUploadHash'] = settings_upload_hash

        # if this image is part of a projet, the project UUID
        image_description["MAPSettingsProject"] = project

    assert("MAPSequenceUUID" in image_description)

    if output_file is not None:
        shutil.copy(filename, output_file)
        filename = output_file

    # write to file
    json_desc = json.dumps(image_description)
    metadata = ExifEdit(filename)
    metadata.add_image_description(json_desc)
    metadata.add_orientation(image_description.get("MAPOrientation", 1))
    metadata.add_direction(image_description["MAPCompassHeading"]["TrueHeading"])
    metadata.add_lat_lon(image_description["MAPLatitude"], image_description["MAPLongitude"])
    date_time = datetime.datetime.strptime(image_description["MAPCaptureTime"]+"000", "%Y_%m_%d_%H_%M_%S_%f")
    metadata.add_date_time_original(date_time)
    metadata.write()


def add_exif_data(filename, data, output_file=None):
    """Add minimal exif data to an image"""
    if output_file is not None:
        shutil.copy(filename, output_file)
        filename = output_file
    metadata = ExifEdit(filename)
    metadata.add_orientation(data.get("orientation", 1))
    metadata.add_direction(data.get("bearing", 0))
    metadata.add_lat_lon(data["lat"], data["lon"])
    metadata.add_date_time_original(data["capture_time"])
    metadata.add_camera_make_model(data["make"], data["model"])
    metadata.write()

class ExifEdit(object):

    def __init__(self, filename):
        """Initialize the object"""
        self.filename = filename
        self.ef = None

        if (type(filename) is str) or (type(filename) is unicode):
            self.ef = JpegFile.fromFile(filename)
        else:
            filename.seek(0)
            self.ef = JpegFile.fromString(filename.getvalue())
        try:
            if (type(filename) is str) or (type(filename) is unicode):
                self.ef = JpegFile.fromFile(filename)
            else:
                filename.seek(0)
                self.ef = JpegFile.fromString(filename.getvalue())
        except IOError:
            etype, value, traceback = sys.exc_info()
            print >> sys.stderr, "Error opening file:", value
        except JpegFile.InvalidFile:
            etype, value, traceback = sys.exc_info()
            print >> sys.stderr, "Error opening file:", value

    def add_image_description(self, dict):
        """Add a dict to image description."""
        if self.ef is not None:
            self.ef.exif.primary.ImageDescription = json.dumps(dict)

    def add_orientation(self, orientation):
        """Add image orientation to image."""
        self.ef.exif.primary.Orientation = [orientation]

    def add_date_time_original(self, date_time):
        """Add date time original."""
        self.ef.exif.primary.ExtendedEXIF.DateTimeOriginal = date_time.strftime('%Y:%m:%d %H:%M:%S')

    def add_lat_lon(self, lat, lon):
        """Add lat, lon to gps (lat, lon in float)."""
        self.ef.set_geo(float(lat), float(lon))

    def add_camera_make_model(self, make, model):
        ''' Add camera make and model.'''
        self.ef.exif.primary.Make = make
        self.ef.exif.primary.Model = model

    def add_dop(self, dop, perc=100):
        """Add GPSDOP (float)."""
        self.ef.exif.primary.GPS.GPSDOP = [Rational(abs(dop * perc), perc)]

    def add_altitude(self, altitude, precision=100):
        """Add altitude (pre is the precision)."""
        ref = '\x00' if altitude > 0 else '\x01'
        self.ef.exif.primary.GPS.GPSAltitude = [Rational(abs(altitude * precision), precision)]
        self.ef.exif.primary.GPS.GPSAltitudeRef = [ref]

    def add_direction(self, direction, ref="T", precision=100):
        """Add image direction."""
        self.ef.exif.primary.GPS.GPSImgDirection = [Rational(abs(direction * precision), precision)]
        self.ef.exif.primary.GPS.GPSImgDirectionRef = ref

    def write(self, filename=None):
        """Save exif data to file."""
        try:
            if filename is None:
                filename = self.filename
            self.ef.writeFile(filename)
        except IOError:
            type, value, traceback = sys.exc_info()
            print >> sys.stderr, "Error saving file:", value

    def write_to_string(self):
        """Save exif data to StringIO object."""
        return self.ef.writeString()

    def write_to_file_object(self):
        """Save exif data to file object."""
        return self.ef.writeFd()

