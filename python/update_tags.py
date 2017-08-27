 #!/usr/bin/python

import os
import argparse
import json
from lib.geo import offset_bearing
from lib.sequence import Sequence
from lib.exifedit import ExifEdit
from lib.exif import EXIF

'''
Interpolates the direction of an image based on the coordinates stored in
the EXIF tag of the next image in a set of consecutive images.

Uses the capture time in EXIF and looks up an interpolated lat, lon, bearing
for each image, and writes the values to the EXIF of the image.

An offset angle relative to the direction of movement may be given as an optional
argument to compensate for a sidelooking camera. This angle should be positive for
clockwise offset. eg. 90 for a rightlooking camera and 270 for a left looking camera

Image orientation can be overridden when needed (false reading from orientation sensor).

Updates Mapillary tags in JSON object stored in description field.

@author: mprins, kolesar-andras
@license: MIT
'''

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Update EXIF tags (both standard tags and Mapillary JSON object stored in description)')
    parser.add_argument('path', help='path to image folder (all images will be processed)')

    parser.add_argument('--interpolate-heading', action='store_true',
                        dest='interpolate',
                        help='interpolate heading values from GPS coordinates of sequence instead of using measured value')

    parser.add_argument('--heading-offset',
                        dest='offset',
                        type=float,
                        default=0.0,
                        help='adds an angle to heading if camera was not directed to front')

    parser.add_argument('--orientation',
                        type=int,
                        dest='orientation',
                        help='override camera orientation sensor value if shake resulted false values (in clockwise degrees: 0, 90, 180 or 270)')

    parser.add_argument('--keep-timestamp', action='store_true',
                        dest='timestamp',
                        help='keep original timestamp of image file')

    parser.add_argument('--backup', action='store_true',
                        dest='backup',
                        help='store backup of overwritten values in Mapillary JSON')


    args = parser.parse_args()

    # see http://sylvana.net/jpegcrop/exif_orientation.html
    orientations = {
        0: 1,
        90: 6,
        180: 3,
        270: 8
    }

    if args.orientation is not None:
        exifOrientation = orientations[args.orientation]

    s = Sequence(args.path)
    if args.interpolate:
        bearings = s.interpolate_direction()

    for filename in s.get_file_list(args.path):
        stat = os.stat(filename)
        exifRead = EXIF(filename)
        mapillaryTag = json.loads(exifRead.extract_image_description())

        if args.interpolate:
            bearing = bearings[filename]
        else:
            bearing = exifRead.extract_direction()

        if args.offset:
            bearing = offset_bearing(bearing, args.offset)

        exifEdit = ExifEdit(filename)

        if args.interpolate or args.offset:
            exifEdit.add_direction(bearing, precision=10)
            if (args.backup):
                if 'backup' not in mapillaryTag: mapillaryTag['backup'] = {}
                if 'MAPCompassHeading' not in mapillaryTag['backup']: mapillaryTag['backup']['MAPCompassHeading'] = {}
                mapillaryTag['backup']['MAPCompassHeading']['TrueHeading'] = mapillaryTag['MAPCompassHeading']['TrueHeading']
            mapillaryTag['MAPCompassHeading']['TrueHeading'] = round(bearing, 1)

        if args.orientation is not None:
            exifEdit.add_orientation(exifOrientation)

            if (args.backup and (mapillaryTag['MAPCameraRotation'] != str(args.orientation))):
                if 'backup' not in mapillaryTag: mapillaryTag['backup'] = {}
                mapillaryTag['backup']['MAPCameraRotation'] = mapillaryTag['MAPCameraRotation']

            mapillaryTag['MAPOrientation'] = exifOrientation
            mapillaryTag['MAPCameraRotation'] = str(args.orientation)

        exifEdit.add_image_description(mapillaryTag)
        exifEdit.write()

        if args.timestamp:
            os.utime(filename, (stat.st_atime, stat.st_mtime))
