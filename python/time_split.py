#!/usr/bin/python

import sys
import os
from datetime import datetime
import exifread


'''
Script for organizing images into sequence groups based on
a cutoff time. This is useful as a step before uploading
lots of photos with the manual uploader.

If you used a camera with a 2s timer and took lots of sequences,
running this script with a 3s cutoff will produce nice subfolders,
one for each sequence.

If no cutoff time is given, one will be estimated based on the median
time difference.
'''


def read_capture_time(filepath):
    '''
    Use exifread to parse capture time from EXIF.
    '''
    time_tag = "EXIF DateTimeOriginal"

    with open(filepath, 'rb') as f:
        tags = exifread.process_file(f)

    # read and format capture time
    if time_tag in tags:
        capture_time = tags[time_tag].values
        capture_time = capture_time.replace(" ","_")
        capture_time = capture_time.replace(":","_")
    else:
        capture_time = 0

    # return as datetime object
    return datetime.strptime(capture_time, '%Y_%m_%d_%H_%M_%S')


def sort_file_list(file_list):
    '''
    Read capture times and sort files in time order.
    '''
    capture_times = [read_capture_time(filepath) for filepath in file_list]
    sorted_times_files = zip(capture_times, file_list)
    sorted_times_files.sort()
    return zip(*sorted_times_files)


def move_groups(groups):
    '''
    Move the files in the groups to new folders.
    '''
    print("Organizing into {0} groups.".format(len(groups)))
    for i,group in enumerate(groups):
        group_path = os.path.dirname(group[0])
        new_dir = os.path.join(group_path, str(i))
        if not os.path.exists(new_dir):
            os.mkdir(new_dir)

        for filepath in group:
            os.rename(filepath, os.path.join(new_dir, os.path.basename(filepath)))
        print("Moved {0} photos to {1}".format(len(group), new_dir))




if __name__ == '__main__':
    '''
    Use from command line as: python time_split.py path cutoff_time
    '''

    if len(sys.argv) > 3:
        print("Usage: python time_split.py path cutoff_time")
        raise IOError("Bad input parameters.")

    path = sys.argv[1]

    file_list = []
    for root, sub_folders, files in os.walk(path):
        file_list += [os.path.join(root, filename) for filename in files if filename.lower().endswith(".jpg")]

    # sort based on EXIF capture time
    capture_times, file_list = sort_file_list(file_list)

    # diff in capture time
    capture_deltas = [t2-t1 for t1,t2 in zip(capture_times, capture_times[1:])]

    # if cutoff time is given use that, else assume cutoff is 1.5x median time delta
    if len(sys.argv)==3:
        cutoff_time = float(sys.argv[2])
    else:
        median = sorted(capture_deltas)[len(capture_deltas)//2]
        cutoff_time = 1.5*median.total_seconds()

    # extract groups by cutting using cutoff time
    groups = []
    group = [file_list[0]]
    for i,filepath in enumerate(file_list[1:]):
        if capture_deltas[i].total_seconds() > cutoff_time:
            # delta too big, save current group, start new
            groups.append(group)
            group = [filepath]
        else:
            group.append(filepath)
    groups.append(group)

    # move groups to subfolders
    move_groups(groups)

    print("Done grouping photos.")
