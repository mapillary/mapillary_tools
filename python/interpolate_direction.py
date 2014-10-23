#!/usr/bin/python

import os, sys, pyexiv2

from pyexiv2.utils import make_fraction
from geotag_from_gpx import compute_bearing


'''
Interpolates the direction of an image based on the coordinates stored in 
the EXIF tag of the next image in a set of consecutive images.

Uses the capture time in EXIF and looks up an interpolated lat, lon, bearing
for each image, and writes the values to the EXIF of the image.

@attention: Requires pyexiv2; see install instructions at http://tilloy.net/dev/pyexiv2/
@author: mprins
@license: MIT
'''

def DMStoDD(degrees, minutes, seconds, hemisphere):
    ''' Convert from degrees, minutes, seconds to decimal degrees. '''
    dms = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    if hemisphere == "W" or hemisphere == "S":
        dms = -1 * dms

    return dms


def list_images(directory):
    ''' 
    Create a list of image tuples sorted by capture timestamp.
    @param directory: directory with JPEG files 
    @return: a list of image tuples with time, directory, lat,long...
    '''
    file_list = []
    for root, sub_folders, files in os.walk(directory):
        file_list += [os.path.join(root, filename) for filename in files if filename.lower().endswith(".jpg")]

    files = []
    # get GPS data from the images and sort the list by timestamp
    for filepath in file_list:
        metadata = pyexiv2.ImageMetadata(filepath)
        metadata.read()
        try:
            t = metadata["Exif.Photo.DateTimeOriginal"].value
            lat = metadata["Exif.GPSInfo.GPSLatitude"].value
            latRef = metadata["Exif.GPSInfo.GPSLatitudeRef"].value
            lon = metadata["Exif.GPSInfo.GPSLongitude"].value
            lonRef = metadata["Exif.GPSInfo.GPSLongitudeRef"].value
            # assume that metadata["Exif.GPSInfo.GPSMapDatum"] is "WGS-84"
            dmslat = DMStoDD(lat[0], lat[1], lat[2], latRef)
            dmslon = DMStoDD(lon[0], lon[1], lon[2], lonRef)
            files.append((t, filepath, dmslat, dmslon))
        except KeyError, e:
            # if any of the required tags are not set the image is not added to the list
            print("Skipping {0}: {1}".format(filename, e))

    files.sort()
    return files


def write_direction_to_image(filename, direction):
    ''' 
    Write the direction to the exif tag of the photograph.
    @param filename: photograph filename
    @param direction: direction of view in degrees
    '''
    metadata = pyexiv2.ImageMetadata(filename)
    metadata.read()

    exiv_direction = make_fraction(int(direction * 10), 10)
    try:
        metadata["Exif.GPSInfo.GPSImgDirection"] = exiv_direction
        metadata["Exif.GPSInfo.GPSImgDirectionRef"] = "T"
        metadata.write()
        print("Added direction to: {0} ({1} degrees)".format(filename, float(exiv_direction)))
    except ValueError, e:
        print("Skipping {0}: {1}".format(filename, e))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python interpolate_direction.py path")
        raise IOError("Bad input parameters.")
    path = sys.argv[1]

    # list of file tuples sorted by timestamp
    imageList = list_images(path)

    # calculate and write direction by looking at next file in the list of files
    for curImg, nextImg in zip(imageList, imageList[1:]):
        direction = compute_bearing(curImg[2], curImg[3], nextImg[2], nextImg[3])
        write_direction_to_image(curImg[1], direction)
    # the last image gets the same direction as the second to last
    write_direction_to_image(nextImg[1], direction)
        
