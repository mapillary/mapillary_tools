from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import datetime
import struct # Only to catch struct.error due to error in PIL / Pillow.

# Original:  https://gist.github.com/erans/983821
# License:   MIT
# Credits:   https://gist.github.com/erans

class ExifException(Exception):
  def __init__(self, message):
    self.message = message
  def __str__(self):
    return self.message

class PILExifReader:
  def __init__(self, filepath):
    self.filepath = filepath
    self.image = Image.open(filepath)
    self.exif = self.get_exif_data(self.image)
  def get_exif_data(self, image):
    """Returns a dictionary from the exif data of an PIL Image item. Also converts the GPS Tags"""
    exif_data = {}
    try:
      info = image._getexif()
    except OverflowError, e:
      if e.message == "cannot fit 'long' into an index-sized integer":
        # Error in PIL when exif data is corrupt.
        return None 
      else:
        raise e
    except struct.error, e: 
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

  def _get_if_exist(self, data, key):
    if key in data:
      return data[key]
    else:
      return None
          
  def _convert_to_degress(self, value):
    """Helper function to convert the GPS coordinates stored in the EXIF to degrees in float format"""
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
    """Returns the latitude and longitude, if available, from the provided exif_data (obtained through get_exif_data above)"""
    lat = None
    lon = None

    gps_info = self.getGpsInfo()
    if gps_info == None:
      return None

    gps_latitude = self._get_if_exist(gps_info, "GPSLatitude")
    gps_latitude_ref = self._get_if_exist(gps_info, 'GPSLatitudeRef')
    gps_longitude = self._get_if_exist(gps_info, 'GPSLongitude')
    gps_longitude_ref = self._get_if_exist(gps_info, 'GPSLongitudeRef')

    if gps_latitude and gps_latitude_ref and gps_longitude and gps_longitude_ref:
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
      
  def calcTuple(self, tup):
    if tup == None or len(tup) != 2 or tup[1] == 0:
      return None
    return int(tup[0]) / int(tup[1])
    
  def getGpsInfo(self):
    if self.exif == None or not "GPSInfo" in self.exif:
      return None
    else:
      return self.exif["GPSInfo"]
    
  def getRotation(self):
    """Returns the direction of the GPS receiver in degrees."""
    gps_info = self.getGpsInfo()
    if gps_info == None:
      return None

    gps_direction = self._get_if_exist(gps_info, "GPSTrack")
    if gps_direction == None:
      return None
    if len(gps_direction) < 2 or gps_direction[1] == 0:
      return None
    direction = self.calcTuple(gps_direction)
    return direction

  def getSpeed(self):
    """Returns the GPS speed in km/h or None if it does not exists."""
    gps_info = self.getGpsInfo()
    if gps_info == None:
      return None
    
    if not "GPSSpeed" in gps_info or not "GPSSpeedRef" in gps_info:
      return None
    speedFrac = gps_info["GPSSpeed"]
    speedRef = gps_info["GPSSpeedRef"]
    
    speed = self.calcTuple(speedFrac)
    if speed == None or speedRef == None:
      return None

    speedRef = speedRef.lower()
    if speedRef == "k":
      pass # km/h - we are happy.
    elif speedRef == "m":
      #Miles pr. hour => km/h
      speed *= 1.609344
    elif speedRef == "n":
      # Knots => km/h
      speed *= 1.852
    else:
      print "Warning: Unknown format for GPS speed '%s' in '%s'." % (speedRef, self.filepath)
      print "Please file a bug and attache the image."
      return None
    return speed

  def isOKNum(self, val, minVal, maxVal):
    try:
      num = int(val)
    except ValueError:
      return False
    if num < minVal or num > maxVal:
      return False
    return True

  def getTime(self):
    # Example data
    # GPSTimeStamp': ((9, 1), (14, 1), (9000, 1000))
    # 'GPSDateStamp': u'2015:05:17'
    gps_info = self.getGpsInfo()
    if gps_info == None:
      return None
    
    if not 'GPSTimeStamp' in gps_info or not 'GPSDateStamp' in gps_info:
      return None
    timestamp = gps_info['GPSTimeStamp']
    datestamp = gps_info['GPSDateStamp']

    if len(timestamp) != 3:
      raise ExifException("Timestamp does not have length 3: %s" % len(timestamp))
    (timeH, timeM, timeS) = timestamp
    h = self.calcTuple(timeH)
    m = self.calcTuple(timeM)
    s = self.calcTuple(timeS)
    if None in (h, m, s):
      raise ExifException("Hour, minute or second is not valid: '%s':'%s':'%s'." % (timeH, timeM, timeS))

    if datestamp.count(':') != 2:
      raise ExifException("Datestamp does not contain 2 colons: '%s'" % datestamp)
    (y, mon, d) = [int(str) for str in datestamp.split(':')]
    if not self.isOKNum(y, 1970, 2100) or not self.isOKNum(mon, 1, 12) or not self.isOKNum(d, 1, 31):
      raise ExifException("Date parsed from the following is not OK: '%s'" % datestamp)

    return datetime.datetime(y, mon, d, h, m, s);
