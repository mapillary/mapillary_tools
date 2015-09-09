#!/usr/bin/python

import getopt
import os
import sys
from math import asin, cos, radians, sin, sqrt

from PIL import Image

from lib_gps_exif import PILExifReader


class GPSDirectionDuplicateFinder:
    """Finds duplicates based on the direction the camera is pointing.
  This supports the case where a panorama is being made."""

    def __init__(self, max_diff):
        self._prev_rotation = None
        self._prev_unique_rotation = None
        self._max_diff = max_diff
        self._latest_text = ""

    def get_latest_text(self):
        return self._latest_text

    def latest_is_duplicate(self, is_duplicate):
        if not is_duplicate:
            self._prev_unique_rotation = self._prev_rotation

    def is_duplicate(self, file_path, exif_reader):
        rotation = exif_reader.get_rotation()

        if rotation is None:
            return None

        if self._prev_unique_rotation is None:
            self._prev_rotation = rotation
            return False

        diff = abs(rotation - self._prev_unique_rotation)
        is_duplicate = diff < self._max_diff

        self._prev_rotation = rotation
        self._latest_text = str(int(diff)) + " deg: " + str(is_duplicate)
        return is_duplicate


class GPSDistance:
    """Calculates the distance between two sets of GPS coordinates."""

    @staticmethod
    def get_gps_distance(lat1, lon1, lat2, lon2):
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
        a = (sin(difflat / 2) ** 2) + (cos(lat1) * cos(lat2) * sin(difflon / 2)
                                       ** 2)
        difflon = lon2 - lon1
        c = 2 * asin(sqrt(a))
        r = 6371000  # Radius of The Earth in meters.
        # It is not a perfect sphere, so this is just good enough.
        return c * r


class GPSSpeedErrorFinder:
    """Finds images in a sequence that might have an error in GPS data
     or suggest a track to be split. It is done by looking at the
     speed it would take to travel the distance in question."""

    def __init__(self, max_speed_km_h, way_too_high_speed_km_h):
        self._prev_lat_lon = None
        self._previous = None
        self._latest_text = ""
        self._previous_filepath = None
        self._max_speed_km_h = max_speed_km_h
        self._way_too_high_speed_km_h = way_too_high_speed_km_h
        self._high_speed = False
        self._too_high_speed = False

    def set_verbose(self, verbose):
        self.verbose = verbose

    def get_latest_text(self):
        return self._latest_text

    def is_error(self, file_path, exif_reader):
        """
    Returns if there is an obvious error in the images exif data.
    The given image is an instance of PIL's Image class.
    the given exif is the data from the get_exif_data function.
    """
        speed_gps = exif_reader.get_speed()
        if speed_gps is None:
            self._latest_text = "No speed given in EXIF data."
            return False
        self._latest_text = "Speed GPS: " + str(speed_gps) + " km/h"
        if speed_gps > self._way_too_high_speed_km_h:
            self._latest_text = ("GPS speed is unrealistically high: %s km/h."
                % speed_gps)
            self._too_high_speed = True
            return True
        elif speed_gps > self._max_speed_km_h:
            self._latest_text = ("GPS speed is high: %s km/h."
                % speed_gps )
            self._high_speed = True
            return True

        latlong = exif_reader.get_lat_lon()
        timestamp = exif_reader.get_time()

        if self._prev_lat_lon is None or self._prev_time is None:
            self._prev_lat_lon = latlong
            self._prev_time = timestamp
            self._previous_filepath = file_path
            return False

        if latlong is None or timestamp is None:
            return False
        diff_meters = GPSDistance.get_gps_distance(
            self._prev_lat_lon[0], self._prev_lat_lon[1], latlong[0],
            latlong[1])
        diff_secs = (timestamp - self._prev_time).total_seconds()

        if diff_secs == 0:
            return False
        speed_km_h = (diff_meters / diff_secs) * 3.6

        if speed_km_h > self._way_too_high_speed_km_h:
            self._latest_text = ("Speed between %s and %s is %s km/h, which is"
            " unrealistically high." % (self._previous_filepath, file_path,
                                          int(speed_km_h)))
            self._too_high_speed = True
            return True
        elif speed_km_h > self._max_speed_km_h:
            self._latest_text = "Speed between %s and %s is %s km/h." % (
                self._previous_filepath, file_path, int(speed_km_h)
            )
            self._high_speed = True
            return True
        else:
            return False

    def is_fast(self):
      return self._high_speed

    def is_too_fast(self):
      return self._too_high_speed


class GPSDistanceDuplicateFinder:
    """Finds duplicates images by looking at the distance between
  two GPS points."""

    def __init__(self, distance):
        self._distance = distance
        self._prev_lat_lon = None
        self._previous = None
        self._latest_text = ""
        self._previous_filepath = None
        self._prev_unique_lat_lon = None

    def get_latest_text(self):
        return self._latest_text

    def latest_is_duplicate(self, is_duplicate):
        if not is_duplicate:
            self._prev_unique_lat_lon = self._prev_lat_lon

    def is_duplicate(self, file_path, exif_reader):
        """
    Returns if the given image is a duplicate of the previous image.
    The given image is an instance of PIL's Image class.
    the given exif is the data from the get_exif_data function.
    """
        latlong = exif_reader.get_lat_lon()

        if self._prev_lat_lon is None:
            self._prev_lat_lon = latlong
            return False

        if self._prev_unique_lat_lon is not None and latlong is not None:
            diff_meters = GPSDistance.get_gps_distance(
                self._prev_unique_lat_lon[0], self._prev_unique_lat_lon[1],
                latlong[0], latlong[1])
            self._previous_filepath = file_path
            is_duplicate = diff_meters <= self._distance
            self._prev_lat_lon = latlong
            self._latest_text = file_path + ": " + str(
                int(diff_meters)) + " m: " + str(is_duplicate)
            return is_duplicate
        else:
           return False


class ImageRemover:
    """Moves images that are (almost) duplicates or contains errors in GPS
  data into separate directories."""

    def __init__(self, src_dir, duplicate_dir, error_dir):
        self._testers = []
        self._error_finders = []
        self._src_dir = src_dir
        self._duplicate_dir = duplicate_dir
        self._error_dir = error_dir
        self._dryrun = False
        self.verbose = 0

    def set_verbose(self, verbose):
        self.verbose = verbose

    def set_dry_run(self, dryrun):
        self._dryrun = dryrun

    def add_duplicate_finder(self, tester):
        self._testers.append(tester)

    def add_error_finder(self, finder):
        self._error_finders.append(finder)

    def _move_into_error_dir(self, file):
        self._move_into_dir(file, self._error_dir)

    def _move_into_duplicate_dir(self, file):
        self._move_into_dir(file, self._duplicate_dir)

    def _move_into_dir(self, file, dir):
        if not self._dryrun and not os.path.exists(dir):
            os.makedirs(dir)
        filename = os.path.basename(file)
        if not self._dryrun:
            os.rename(file, os.path.join(dir, filename))
        print file, " => ", dir

    def _read_capture_time(self, filepath):
        reader = PILExifReader(filepath)
        return reader.read_capture_time()

    def _sort_file_list(self, file_list):
        '''
        Read capture times and sort files in time order.
        '''
        capture_times = [self._read_capture_time(filepath) for filepath in file_list]
        sorted_times_files = zip(capture_times, file_list)
        sorted_times_files.sort()
        return zip(*sorted_times_files)

    def do_magic(self):
        """Perform the task of finding and moving images."""
        files = [os.path.join(self._src_dir, f) for f in os.listdir(self._src_dir)
                 if os.path.isfile(os.path.join(self._src_dir, f)) and
                 f.lower().endswith('.jpg')]

        capturetime, files = self._sort_file_list(files)

        for file_path in files:
            #print file_path
            exif_reader = PILExifReader(file_path)
            is_error = self._handle_possible_erro(file_path, exif_reader)
            if not is_error:
                self._handle_possible_duplicate(file_path, exif_reader)

    def _handle_possible_duplicate(self, file_path, exif_reader):
        is_duplicate = True
        verbose_text = []
        for tester in self._testers:
            is_this_duplicate = tester.is_duplicate(file_path, exif_reader)
            if is_this_duplicate != None:
              is_duplicate &= is_this_duplicate
              verbose_text.append(tester.get_latest_text())
            else:
              verbose_text.append("No orientation")

        if self.verbose >= 1:
            print ", ".join(verbose_text), "=>", is_duplicate
        if is_duplicate:
            self._move_into_duplicate_dir(file_path)
        for tester in self._testers:
            tester.latest_is_duplicate(is_duplicate)
        return is_duplicate

    def _handle_possible_erro(self, file_path, exif_reader):
        is_error = False
        for finder in self._error_finders:
            err = finder.is_error(file, exif_reader)
            if err:
                print finder.get_latest_text()
            is_error |= err
        if is_error:
            self._move_into_error_dir(file_path)
        return is_error


if __name__ == "__main__":
    distance = 4
    pan = 20
    error_dir = "errors"
    fast_km_h = 150
    too_fast_km_h = 200
    min_duplicates = 3

    def print_help():
        print """Usage: remove-duplicates.py [-h | -d] src_dir duplicate_dir
    Finds images in src_dir and moves duplicates to duplicate_dir.

    Both src_dir and duplicate_dir are mandatory. If src_dir is not .
    and duplicate_dir is not given, it will be named "duplicate" and put
    in the current directory.
    If duplicate_dir does not exist, it will be created in the current
    directory (no matter if it will be used or not).

    In order to be considered a duplicate, the image must match ALL criteria
    to be a duplicate. With default settings that is, it must have travelled
    less than """ + str(distance) + """  meters and be panned less than """ \
        "" + str(pan) + """ degrees.
    This supports that you ride straight ahead with a significant speed,
    that you make panoramas standing still and standing still waiting for
    the red light to change into green.

    Important: The upload.py from Mapillary uploads *recursively* so do not
    put the duplicate_dir under the dir your are uploading from!

    Options:
    -e --error-dir Give the directory to put pictures into, if they
                   contains obvious errors.
                   Default value is""" + error_dir + """
    -h --help      Print this message and exit.
    -d --distance  Give the maximum distance in meters images must be taken
                   not to be considered duplicates. Default is """ \
        "" + str(distance) + """ meters.
                   The distance is calculated from embedded GPS data. If there
                   is no GPS data the images are ignored.
    -a --fast      The speed (km/h) which is a bit too fast.
                   E.g. 40 for a bicycle.
                   Default value is: """ + str(fast_km_h) + """ km/h
    -t --too-fast  The speed (km/h) which is way too fast.
                   E.g. 70 for a bicycle.
                   Default value is: """ + str(too_fast_km_h) + """ km/h
    -p --pan       The maximum distance in degrees (0-360) the image must be
                   panned in order not to be considered a duplicate.
                   Default is""" + str(pan) + """ degrees.
    -m --min-dup   Minimum duplicates for a duplicate to be removed.
                   Default is """  + str(min_duplicates), """.
                   When larger than 0 the duplicate feature is only used to
                   remove images due to larger stops, like a red traffic
                   light. If going really slow this will also cause moving
                   images.
                   When 0 individual images are also moved, when the speed
                   is slow, images will be moved giving a more consistent
                   expirience when viewing them one by one.
    -n --dry-run   Do not move any files. Just simulate.
    -v --verbose   Print extra info.
    """

    dryrun = False
    verbose = 0
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hd:p:nve:m:a:t:",
                                   ["help", "distance=", "pan=", "dry-run",
                                    "verbose", "error-dir", "min-dup",
                                    "fast=", "too-fast="])
    except getopt.GetoptError, err:
        print str(err)
        sys.exit(2)
    for switch, value in opts:
        if switch in ("-h", "--help"):
            print_help()
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
            error_dir = value
        elif switch in ("-m", "--min-dup"):
            min_duplicates = int(value)
        elif switch in ("-a", "--fast"):
            fast_km_h = float(value)
        elif switch in ("-t", "--too-fast"):
            too_fast_km_h = float(value)

    if len(args) == 1 and args[0] != ".":
        duplicate_dir = "duplicates"
    elif len(args) < 2:
        print_help()
        sys.exit(2)
    else:
        duplicate_dir = args[1]

    src_dir = args[0]

    distance_finder = GPSDistanceDuplicateFinder(distance)
    direction_finder = GPSDirectionDuplicateFinder(pan)
    speed_error_finder = GPSSpeedErrorFinder(fast_km_h, too_fast_km_h)

    image_remover = ImageRemover(src_dir, duplicate_dir, error_dir)
    image_remover.set_dry_run(dryrun)
    image_remover.set_verbose(verbose)

    # Modular: Multiple testers can be added.
    image_remover.add_duplicate_finder(distance_finder)
    image_remover.add_duplicate_finder(direction_finder)
    image_remover.add_error_finder(speed_error_finder)

    try:
        image_remover.do_magic()
    except KeyboardInterrupt:
        print "You cancelled."
        sys.exit(1)
    finally:
        show_split = False
        if speed_error_finder.is_fast():
            show_split = True
            print
            print ("It looks like you have gone really fast between"
                +" some images.")
            print "Strongly consider splitting them into multiple series."
            print "See the messages earlier."
        if speed_error_finder.is_too_fast():
            show_split = True
            print
            print ("It looks like yo have gone unrealistically fast"
                 + "between some images to be ok.")
            print ("Mabye your GPS started out with a wrong location "
                 + "or you traveled between sets?")
            print "See the messages earlier."
        if show_split:
            print
            print ("See http://blog.mapillary.com/update/2014/06/16/actioncam-workflow.html"
                + " on how")
            print ("to use time_split.py to automatically split a lot "
                + "of images into multiple series.")
