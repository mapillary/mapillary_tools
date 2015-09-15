import os
import sys
import lib.io
import lib.geo
from lib.exif import EXIF

'''
Sequence class for organizing/cleaning up photos in a folder
    - split to sequences based on time intervals
    - split to sequences based on gps distances
    - remove duplicate images (e.g. waiting for red light, in traffic etc)
@contributors:
'''

class Sequence(object):

    def __init__(self, filepath):
        self.filepath = filepath
        self.get_file_list(filepath)

    def get_file_list(self, filepath):
        file_list = []
        for root, sub_folders, files in os.walk(self.filepath):
            file_list += [os.path.join(root, filename) for filename in files if filename.lower().endswith(".jpg")]
        self.file_list = file_list
        return file_list

    def read_capture_time(self, filename):
        '''
        Use EXIF class to parse capture time from EXIF.
        '''
        exif = EXIF(filename)
        return exif.extract_capture_time()

    def read_lat_lon(self, filename):
        exif = EXIF(filename)
        lon, lat = exif.extract_lon_lat()
        return lat, lon

    def sort_file_list(self, file_list):
        '''
        Read capture times and sort files in time order.
        '''
        capture_times = [self.read_capture_time(filepath) for filepath in file_list]
        sorted_times_files = zip(capture_times, file_list)
        sorted_times_files.sort()
        return zip(*sorted_times_files)

    def move_groups(self, groups):
        '''
        Move the files in the groups to new folders.
        '''
        print("Organizing into {0} groups.".format(len(groups)))
        for i,group in enumerate(groups):
            group_path = os.path.dirname(group[0])
            new_dir = os.path.join(group_path, str(i))
            lib.io.mkdir_p(new_dir)
            for filepath in group:
                os.rename(filepath, os.path.join(new_dir, os.path.basename(filepath)))
            print("Moved {0} photos to {1}".format(len(group), new_dir))

    def split(self, cutoff_distance=500., cutoff_time=None):
        '''
        Split photos into sequences in case of large distance gap or large time interval
        @params cutoff_distance: maximum distance gap in meters
        @params cutoff_time:     maximum time interval in seconds
        '''

        file_list = self.file_list

        # sort based on EXIF capture time
        capture_times, file_list = self.sort_file_list(file_list)

        # diff in capture time
        capture_deltas = [t2-t1 for t1,t2 in zip(capture_times, capture_times[1:])]

        # read gps for ordered files
        latlons = [self.read_lat_lon(filepath) for filepath in file_list]

        # distance between consecutive images
        distances = [lib.geo.gps_distance(ll1, ll2) for ll1, ll2 in zip(latlons, latlons[1:])]

        # if cutoff time is given use that, else assume cutoff is 1.5x median time delta
        if cutoff_time is None:
            median = sorted(capture_deltas)[len(capture_deltas)//2]
            cutoff_time = 1.5*median.total_seconds()

        # extract groups by cutting using cutoff time
        groups = []
        group = [file_list[0]]
        cut = 0
        for i,filepath in enumerate(file_list[1:]):
            cut_time = capture_deltas[i].total_seconds() > cutoff_time
            cut_distance = distances[i] > cutoff_distance
            if cut_time or cut_distance:
                cut += 1
                # delta too big, save current group, start new
                groups.append(group)
                group = [filepath]
                if cut_time:
                    print 'Cut {}: Delta in time {} seconds is too big at {}'.format(cut, capture_deltas[i].total_seconds(), file_list[i+1])
                elif cut_distance:
                    print 'Cut {}: Delta in distance {} meters is too big at {}'.format(cut,distances[i], file_list[i+1])
            else:
                group.append(filepath)
        groups.append(group)

        # move groups to subfolders
        self.move_groups(groups)

        print("Done split photos in {} into {} sequences".format(self.filepath, len(groups)))
        return groups

    def interpolate_direction(self, offset=0):
        '''
        Interpolate bearing of photos in a sequence with an offset
        @author: mprins
        '''

        bearings = {}
        file_list = self.file_list
        num_file = len(file_list)

        if num_file>1:
            # sort based on EXIF capture time
            capture_times, file_list = self.sort_file_list(file_list)

            # read gps for ordered files
            latlons = [self.read_lat_lon(filepath) for filepath in file_list]

            if len(file_list)>1:
                # bearing between consecutive images
                bearings = [lib.geo.compute_bearing(ll1[0], ll1[1], ll2[0], ll2[1])
                                for ll1, ll2 in zip(latlons, latlons[1:])]
                bearings.append(bearings[-1])
                print bearings
                bearings = {file_list[i]: lib.geo.offset_bearing(b, offset) for i, b in enumerate(bearings)}
        elif num_file==1:
            #if there is only one file in the list, just write the direction 0 and offset
            bearings = {file_list[0]: lib.geo.offset_bearing(0.0, offset)}

        return bearings