import datetime
import struct  # Only to catch struct.error due to error in PIL / Pillow.
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

# Original:  https://gist.github.com/erans/983821
# License:   MIT
# Credits:   https://gist.github.com/erans


class ExifException(Exception):
    def __init__(self, message):
        self._message = message

    def __str__(self):
        return self._message


class PILExifReader:
    def __init__(self, filepath):
        self._filepath = filepath
        image = Image.open(filepath)
        self._exif = self.get_exif_data(image)
        image.close()

    def get_exif_data(self, image):
        """Returns a dictionary from the exif data of an PIL Image
        item. Also converts the GPS Tags"""
        exif_data = {}
        try:
            info = image._getexif()
        except OverflowError, e:
            if e.message == "cannot fit 'long' into an index-sized integer":
                # Error in PIL when exif data is corrupt.
                return None
            else:
                raise e
        except struct.error as e:
            if e.message == "unpack requires a string argument of length 2":
                # Error in PIL when exif data is corrupt.
                return None
            else:
                raise e
        if info:
            for tag, value in info.items():
                decoded = TAGS.get(tag, tag)
                if decoded == "GPSInfo":
                    gps_data = {}
                    for t in value:
                        sub_decoded = GPSTAGS.get(t, t)
                        gps_data[sub_decoded] = value[t]
                    exif_data[decoded] = gps_data
                else:
                    exif_data[decoded] = value
        return exif_data

    def read_capture_time(self):
        time_tag = "DateTimeOriginal"

        # read and format capture time
        if self._exif == None:
            print "Exif is none."
        if time_tag in self._exif:
            capture_time = self._exif[time_tag]
            capture_time = capture_time.replace(" ","_")
            capture_time = capture_time.replace(":","_")
        else:
            print "No time tag in "+self._filepath
            capture_time = 0

        # return as datetime object
        return datetime.datetime.strptime(capture_time, '%Y_%m_%d_%H_%M_%S')

    def _get_if_exist(self, data, key):
        if key in data:
            return data[key]
        else:
            return None

    def _convert_to_degress(self, value):
        """Helper function to convert the GPS coordinates stored in
        the EXIF to degrees in float format."""
        d0 = value[0][0]
        d1 = value[0][1]
        d = float(d0) / float(d1)

        m0 = value[1][0]
        m1 = value[1][1]
        m = float(m0) / float(m1)

        s0 = value[2][0]
        s1 = value[2][1]
        s = float(s0) / float(s1)

        return d + (m / 60.0) + (s / 3600.0)

    def get_lat_lon(self):
        """Returns the latitude and longitude, if available, from the
        provided exif_data (obtained through get_exif_data above)."""
        lat = None
        lon = None

        gps_info = self.get_gps_info()
        if gps_info is None:
            return None

        gps_latitude = self._get_if_exist(gps_info, "GPSLatitude")
        gps_latitude_ref = self._get_if_exist(gps_info, 'GPSLatitudeRef')
        gps_longitude = self._get_if_exist(gps_info, 'GPSLongitude')
        gps_longitude_ref = self._get_if_exist(gps_info, 'GPSLongitudeRef')

        if (gps_latitude and gps_latitude_ref
            and gps_longitude and gps_longitude_ref):
            lat = self._convert_to_degress(gps_latitude)
            if gps_latitude_ref != "N":
                lat = 0 - lat

            lon = self._convert_to_degress(gps_longitude)
            if gps_longitude_ref != "E":
                lon = 0 - lon

        if isinstance(lat, float) and isinstance(lon, float):
            return lat, lon
        else:
            return None

    def calc_tuple(self, tup):
        if tup is None or len(tup) != 2 or tup[1] == 0:
            return None
        return int(tup[0]) / int(tup[1])

    def get_gps_info(self):
        if self._exif is None or not "GPSInfo" in self._exif:
            return None
        else:
            return self._exif["GPSInfo"]

    def get_rotation(self):
        """Returns the direction of the GPS receiver in degrees."""
        gps_info = self.get_gps_info()
        if gps_info is None:
            return None

        for tag in ('GPSImgDirection', 'GPSTrack'):
            gps_direction = self._get_if_exist(gps_info, tag)
            direction = self.calc_tuple(gps_direction)
            if direction == None:
                continue
            else:
                return direction
        return None

    def get_speed(self):
        """Returns the GPS speed in km/h or None if it does not exists."""
        gps_info = self.get_gps_info()
        if gps_info is None:
            return None

        if not "GPSSpeed" in gps_info or not "GPSSpeedRef" in gps_info:
            return None
        speed_frac = gps_info["GPSSpeed"]
        speed_ref = gps_info["GPSSpeedRef"]

        speed = self.calc_tuple(speed_frac)
        if speed is None or speed_ref is None:
            return None

        speed_ref = speed_ref.lower()
        if speed_ref == "k":
            pass  # km/h - we are happy.
        elif speed_ref == "m":
            #Miles pr. hour => km/h
            speed *= 1.609344
        elif speed_ref == "n":
            # Knots => km/h
            speed *= 1.852
        else:
            print "Warning: Unknown format for GPS speed '%s' in '%s'." % (
                speed_ref, self._filepath)
            print "Please file a bug and attache the image."
            return None
        return speed

    def is_ok_num(self, val, minVal, maxVal):
        try:
            num = int(val)
        except ValueError:
            return False
        if num < minVal or num > maxVal:
            return False
        return True

    def get_time(self):
        # Example data
        # GPSTimeStamp': ((9, 1), (14, 1), (9000, 1000))
        # 'GPSDateStamp': u'2015:05:17'
        gps_info = self.get_gps_info()
        if gps_info is None:
            return None

        if not 'GPSTimeStamp' in gps_info or not 'GPSDateStamp' in gps_info:
            return None
        timestamp = gps_info['GPSTimeStamp']
        datestamp = gps_info['GPSDateStamp']

        if len(timestamp) != 3:
            raise ExifException("Timestamp does not have length 3: %s" %
                                len(timestamp))
        (timeH, timeM, timeS) = timestamp
        h = self.calc_tuple(timeH)
        m = self.calc_tuple(timeM)
        s = self.calc_tuple(timeS)
        if None in (h, m, s):
            raise ExifException(
                "Hour, minute or second is not valid: '%s':'%s':'%s'." %
                (timeH, timeM, timeS))

        if datestamp.count(':') != 2:
            raise ExifException("Datestamp does not contain 2 colons: '%s'" %
                                datestamp)
        (y, mon, d) = [int(str) for str in datestamp.split(':')]
        if not self.is_ok_num(y, 1970, 2100) or not self.is_ok_num(
                mon, 1, 12) or not self.is_ok_num(d, 1, 31):
            raise ExifException(
                "Date parsed from the following is not OK: '%s'" % datestamp)

        return datetime.datetime(y, mon, d, h, m, s)
