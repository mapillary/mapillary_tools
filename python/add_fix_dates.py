#!/usr/bin/env python

import sys
import os
import datetime
from lib.exifedit import ExifEdit

'''
Script for adding dates to jpg files extracted from video with no tags. if you have a directory of files
provide the directory, the datetime for the first file, and an increment in seconds. Ie if the photos are
taken every 2 seconds
python add_fix_dates.py /home/me/myphotos/ '2014-11-27 13:01:01' 2
You can use local time, that is expected. Maybe GMT if i get to it.

!!! This version needs testing, please report issues.!!!
'''

time_format = "%Y-%m-%d %H:%M:%S"

def add_exif_using_timestamp(filename, start_time, offset_time):
    '''
    Add timestamp to EXIF given start time and offset time.
    '''

    exif = ExifEdit(filename)
    t = start_time + datetime.timedelta(seconds=offset_time)
    print("setting {0} time to {1} due to offset {2}".format(filename, t, offset_time))

    try:
        exif.add_date_time_original(t)
        exif.write()
        print("Added timestamp {} to {}.".format(filename, t.strftime(time_format)))
    except ValueError, e:
        print("Skipping {0}: {1}".format(filename, e))


if __name__ == '__main__':
    '''
    Use from command line as: python add_fix_dates.py images-path StartTime increment-in-seconds
    If you provide a start time and increment, the first photo will be tagged at start time, and
    each subsequent photo will be tagged with prior photo + increment seconds.

    '''
    if len(sys.argv) != 4:
        sys.exit("Usage: %s images-path starttime (yyyy-mm-dd hh:mm:ss) increment-in-seconds" % sys.argv[0])

    path = sys.argv[1]
    start_time = sys.argv[2]
    time_offset = float(sys.argv[3])

    if path.lower().endswith(".jpg"):
        # single file
        file_list = [path]
    else:
        # folder(s)
        file_list = []
        for root, sub_folders, files in os.walk(path):
            file_list += [os.path.join(root, filename) for filename in files
                          if filename.lower().endswith(".jpg")]

    inc = 0
    file_list.sort()
    start_time_dt = datetime.datetime.strptime(start_time, time_format)

    for filepath in file_list:
        add_exif_using_timestamp(filepath, start_time_dt, inc)
        inc = inc + time_offset