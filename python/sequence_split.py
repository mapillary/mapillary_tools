#!/usr/bin/env python

import sys
import os
import argparse
from datetime import datetime
from lib.exif import EXIF
from lib.sequence import Sequence

'''
Script for organizing images into sequence groups based on
a cutoff distance and a cutoff time.
This is useful as a step before uploading lots of photos with the manual uploader.

[cutoff_distance]
If you capture the photos with pauses during your trip, it generally leads to
photos with large distance gaps. Runing this script with a 500-meter cutoff distance
will produce sequences that avoid any gaps larger than 500 meters.

The default cutoff distance is 500 meters.

[cutoff_time]
If you used a camera with a 2s timer and took lots of sequences,
running this script with a 3s cutoff will produce nice subfolders,
one for each sequence.

If no cutoff time is given, one will be estimated based on the median
time difference.
'''

if __name__ == '__main__':
    '''
    Use from command line as: python sequence_split.py path [cutoff_time] [cutoff_distance]
    @params path: path to the photos
    @params cutoff_time: cutoff time in seconds
    @params cutoff_distance: cutoff distance in meters
    '''

    if len(sys.argv) > 4 or len(sys.argv) < 2:
        sys.exit("Usage: python sequence_split.py path [cutoff_time] [cutoff_distance] ")

    path = sys.argv[1]
    cutoff_time = None if len(sys.argv) < 3 else float(sys.argv[2])
    cutoff_distance = 500 if len(sys.argv) < 4 else float(sys.argv[3])

    s = Sequence(path)
    groups = s.split(cutoff_distance=cutoff_distance, cutoff_time=cutoff_time)
