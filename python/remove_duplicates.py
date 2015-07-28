#!/usr/bin/python

import os
import sys
import getopt
from math import radians, cos, sin, asin, sqrt
from lib_gps_exif import PILExifReader
from PIL import Image

class GPSDirectionDuplicateFinder:
  """Finds duplicates based on the direction the camera is pointing.
  This supports the case where a panorama is being made."""
  def __init__(self, maxDiff):
    self.prevRotation = None
    self.prevUniqueRotation = None
    self.maxDiff = maxDiff
    self.latestText = ""
    
  def getLatestText(self):
    return self.latestText
    
  def latestIsDuplicate(self, isDuplicate):
    if not isDuplicate:
      self.prevUniqueRotation = self.prevRotation
  def isDuplicate(self, filepath, exifReader):
    rotation = exifReader.get_rotation()

    if rotation == None:
      return False
      
    if self.prevUniqueRotation == None:
      self.prevRotation = rotation
      return False

    diff = abs(rotation - self.prevUniqueRotation)
    isDuplicate = diff < self.maxDiff

    self.prevRotation = rotation
    self.latestText = str(int(diff))+" deg: "+str(isDuplicate)
    return isDuplicate

class GPSDistance:
  """Calculates the distance between two sets of GPS coordinates."""
  @staticmethod
  def getGPSDistance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees with a result in meters).
      
    This is done using the Haversine Formula.
    """
    # Convert decimal degrees to radians 
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    difflat = lat2 - lat1
    difflon = lon2 - lon1
    a = (sin(difflat / 2) ** 2) + (cos(lat1) * cos(lat2) * sin(difflon / 2) ** 2)
    difflon = lon2 - lon1 
    c = 2 * asin(sqrt(a)) 
    r = 6371000 # Radius of The Earth in meters.
                # It is not a perfect sphere, so this is just good enough.
    return c * r

class GPSSpeedErrorFinder:
  """Finds images in a sequence that might have an error in GPS data
     or suggest a track to be split. It is done by looking at the
     speed it would take to travel the distance in question."""
  def __init__(self, maxSpeedKmH, wayTooHighSpeedKmH):
    self.prevLatLon = None
    self.previous = None
    self.latestText = ""
    self.previousFilepath = None
    self.maxSpeedKmH = maxSpeedKmH
    self.wayTooHighSpeedKmH = wayTooHighSpeedKmH
    self.highSpeed = False
    self.tooHighSpeed = False
    
  def setVerbose(self, verbose):
    self.verbose = verbose
  def getLatestText(self):
    return self.latestText
  def isError(self, filepath, exifReader):
    """
    Returns if there is an obvious error in the images exif data.
    The given image is an instance of PIL's Image class.
    the given exif is the data from the get_exif_data function.
    """
    speedGPS = exifReader.get_speed()
    if speedGPS == None:
      self.latestText = "None or corrupt exif data."
      return True
    self.latestText = "Speed GPS: "+str(speedGPS)+" km/h"
    if speedGPS > self.wayTooHighSpeedKmH:
      self.latestText = "GPS speed is unrealistically high: %s km/h."
      self.tooHighSpeed = True
      return True
    elif speedGPS > self.maxSpeedKmH:
      self.latestText = "GPS speed is high: %s km/h."
      self.highSpeed = True
      return True

    latlong = exifReader.get_lat_lon()
    timestamp = exifReader.get_time()

    if self.prevLatLon == None or self.prevTime == None:
      self.prevLatLon = latlong
      self.prevTime = timestamp
      self.previousFilepath = filepath
      return False
      
    if latlong == None or timestamp == None:
      return False
    diffMeters = GPSDistance.getGPSDistance(self.prevLatLon[0], self.prevLatLon[1], latlong[0], latlong[1])
    diffSecs = (timestamp - self.prevTime).total_seconds()

    if diffSecs == 0:
      return False
    speedKmH = (diffMeters / diffSecs) * 3.6
    
    if speedKmH > self.wayTooHighSpeedKmH:
      self.latestText = "Speed between %s and %s is %s km/h, which is unrealistically high." % (self.previousFilepath, filepath, int(speedKmH))
      self.tooHighSpeed = True
      return True
    elif speedKmH > self.maxSpeedKmH:
      self.latestText = "Speed between %s and %s is %s km/h." % (self.previousFilepath, filepath, int(speedKmH))
      self.highSpeed = True
      return True
    else:
      return False

class GPSDistanceDuplicateFinder:
  """Finds duplicates images by looking at the distance between two GPS points."""
  def __init__(self, distance):
    self.distance = distance
    self.prevLatLon = None
    self.previous = None
    self.latestText = ""
    self.previousFilepath = None
    self.prevUniqueLatLon = None
    
  def getLatestText(self):
    return self.latestText
  def latestIsDuplicate(self, isDuplicate):
    if not isDuplicate:
      self.prevUniqueLatLon = self.prevLatLon
  def isDuplicate(self, filepath, exifReader):
    """
    Returns if the given image is a duplicate of the previous image.
    The given image is an instance of PIL's Image class.
    the given exif is the data from the get_exif_data function.
    """
    latlong = exifReader.get_lat_lon()
    
    if self.prevLatLon == None:
      self.prevLatLon = latlong
      return False

    if self.prevUniqueLatLon != None and latlong != None:
      diffMeters = GPSDistance.getGPSDistance(
              self.prevUniqueLatLon[0], self.prevUniqueLatLon[1], latlong[0], latlong[1])
      self.previousFilepath = filepath
      isDuplicate = diffMeters <= self.distance
      self.prevLatLon = latlong
      self.latestText = str(int(diffMeters)) + " m: "+str(isDuplicate)
      return isDuplicate
    else:
      return False

class ImageRemover:
  """Moves images that are (almost) duplicates or contains errors in GPS data into
  separate directories."""
  def __init__(self, srcDir, duplicateDir, errorDir):
    self.testers = []
    self.errorFinders = []
    self.srcDir = srcDir
    self.duplicateDir = duplicateDir
    self.errorDir = errorDir
    self.dryrun = False
    self.verbose = 0
  def setVerbose(self, verbose):
    self.verbose = verbose
  def setDryRun(self, dryrun):
    self.dryrun = dryrun
  def addDuplicateFinder(self, tester):
    self.testers.append(tester)
  def addErrorFinder(self, finder):
    self.errorFinders.append(finder)
  def moveIntoErrorDir(self, file):
    self.moveIntoDir(file, self.errorDir)
  def moveIntoDuplicateDir(self, file):
    self.moveIntoDir(file, self.duplicateDir)
  def moveIntoDir(self, file, dir):
    if not self.dryrun and not os.path.exists(dir):
      os.makedirs(dir)
    filename = os.path.basename(file)
    if not self.dryrun:
      os.rename(file, os.path.join(dir, filename))
    print file, " => ", dir
       
  def doMagic(self):
    """Perform the task of finding and moving images."""
    files = [f for f in os.listdir(self.srcDir) if os.path.isfile(self.srcDir+'/'+f) and f.lower().endswith('.jpg')]
    list.sort(files)
    
    for file in files:
      filepath = os.path.join(self.srcDir, file)
      exifReader = PILExifReader(filepath)
      isError = self.handlePossibleError(filepath, exifReader)
      if not isError:
        self.handlePossibleDuplicate(filepath, exifReader)
      
  def handlePossibleDuplicate(self, filepath, exifReader):
    isDuplicate = True
    verboseText = []
    for tester in self.testers:
      isDuplicate &= tester.isDuplicate(filepath, exifReader)
      verboseText.append(tester.getLatestText())

    if self.verbose >= 1:
      print ", ".join(verboseText), "=>", isDuplicate
    if isDuplicate:
      self.moveIntoDuplicateDir(filepath)
    for tester in self.testers:
      tester.latestIsDuplicate(isDuplicate)
    return isDuplicate

  def handlePossibleError(self, filepath, exifReader):
    isError = False
    for finder in self.errorFinders:
      err = finder.isError(file, exifReader)
      if err:
        print finder.getLatestText()
      isError |= err
    if isError:
      self.moveIntoErrorDir(filepath)
    return isError
    
if __name__ == "__main__":
  distance = 4
  pan = 20
  errorDir = "errors"
  fastKmH = 150
  tooFastKmH = 200
  def printHelp():
    print """Usage: remove-duplicates.py [-h | -d] srcDir duplicateDir
    Finds images in srcDir and moves duplicates to duplicateDir.
    
    Both srcDir and duplicateDir are mandatory. If srcDir is not .
    and duplicateDir is not given, it will be named "duplicate" and put
    in the current directory.
    If duplicateDir does not exist, it will be created in the current
    directory (no matter if it will be used or not).

    In order to be considered a duplicate, the image must match ALL criteria
    to be a duplicate. With default settings that is, it must have travelled
    less than """+str(distance)+"""  meters and be panned less than """+str(pan)+""" degrees.
    This supports that you ride straight ahead with a significant speed,
    that you make panoramas standing still and standing still waiting for
    the red light to change into green.    

    Important: The upload.py from Mapillary uploads *recursively* so do not
    put the duplicateDir under the dir your are uploading from!
    
    Options:
    -e --error-dir Give the directory to put pictures into, if they contains obvious errors.
                   Default value is """ +errorDir+ """
    -h --help      Print this message and exit.
    -d --distance  Give the maximum distance in meters images must be taken
                   not to be considered duplicates. Default is """+str(distance)+""" meters.
                   The distance is calculated from embedded GPS data. If there
                   is no GPS data the images are ignored.
    -a --fast      The speed (km/h) which is a bit too fast. E.g. 40 for a bicycle.
                   Default value is: """ +str(fastKmH)+ """ km/h
    -t --too-fast  The speed (km/h) which is way too fast. E.g. 70 for a bicycle.
                   Default value is: """ +str(tooFastKmH)+ """ km/h
    -p --pan       The maximum distance in degrees (0-360) the image must be
                   panned in order not to be considered a duplicate.
                   Default is """+str(pan)+""" degrees.
    -n --dry-run   Do not move any files. Just simulate.
    -v --verbose   Print extra info.
    """
    
  dryrun = False
  verbose = 0
  try:
      opts, args = getopt.getopt(sys.argv[1:], "hd:p:nve:",
                    ["help", "distance=", "pan=", "dry-run", "verbose", "error-dir"])
  except getopt.GetoptError, err:
    print str(err)
    sys.exit(2)
  for switch, value in opts:
    if switch in ("-h", "--help"):
      printHelp()
      sys.exit(0)
    elif switch in ("-d", "--distance"):
      distance = float(value)
    elif switch in ("-p", "--pan"):
      pan = float(value)
    elif switch in ("-n", "--dry-run"):
      dryrun = True
    elif switch in ("-v", "--verbose"):
      verbose += 1
    elif switch in ("-e", "--error-dir"):
      errorDir = value
    
  if len(args) == 1 and args[0] != ".":
    duplicateDir = "duplicates"
  elif len(args) < 2:
    printHelp()
    sys.exit(2)
  else:
    duplicateDir = args[1]

  srcDir = args[0]

  distanceFinder = GPSDistanceDuplicateFinder(distance)
  directionFinder = GPSDirectionDuplicateFinder(pan)
  speedErrorFinder = GPSSpeedErrorFinder(fastKmH, tooFastKmH)
  
  imageRemover = ImageRemover(srcDir, duplicateDir, errorDir)
  imageRemover.setDryRun(dryrun)
  imageRemover.setVerbose(verbose)
  
  # Modular: Multiple testers can be added.
  imageRemover.addDuplicateFinder(distanceFinder)
  imageRemover.addDuplicateFinder(directionFinder)
  imageRemover.addErrorFinder(speedErrorFinder)

  try:
    imageRemover.doMagic()
  except KeyboardInterrupt:
    print "You cancelled."
    sys.exit(1)
  if False:
    showSplit = False
    if False and distanceFinder.isLongDistanceBetween():
      showSplit = True
      print
      print "Some of your images have a long distance between them."
      print "Strongly consider splitting them into multiple series."
    if False and distanceFinder.isTooLongDistanceBetween():
      showSplit = True
      print 
      print "Some of your images have way too long a distance between them to be ok."
      print "Mabye your GPS started out with a wrong location or you traveled between sets?"
    if showSplit:
      print
      print "See http://blog.mapillary.com/update/2014/06/16/actioncam-workflow.html on how"
      print "to use time_split.py to automatically split a lot of images into multiple series."

