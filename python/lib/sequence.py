import os
import sys
import lib.io
import lib.geo
from lib.exif import EXIF, verify_exif

'''
Sequence class for organizing/cleaning up photos in a folder
    - split to sequences based on time intervals
    - split to sequences based on gps distances
    - remove duplicate images (e.g. waiting for red light, in traffic etc) @simonmikkelsen
'''

MAXIMUM_SEQUENCE_LENGTH = 6000

class Sequence(object):

    def __init__(self, filepath, skip_folders=[], skip_subfolders=False, check_exif=True):
        self.filepath = filepath
        self._skip_folders = skip_folders
        self._skip_subfolders = skip_subfolders
        self.file_list = self.get_file_list(filepath, check_exif)
        self.num_images = len(self.file_list)

    def _is_skip(self, filepath):
        '''
        Skip photos in specified folders
            - filepath/duplicates: it stores potential duplicate photos
                                   detected by method 'remove_duplicates'
            - filepath/success:    it stores photos that have been successfully
        '''
        _is_skip = False
        for folder in self._skip_folders:
            if folder in filepath:
                _is_skip = True
        if self._skip_subfolders and filepath != self.filepath:
            _is_skip = True
        return _is_skip

    def _read_capture_time(self, filename):
        '''
        Use EXIF class to parse capture time from EXIF.
        '''
        exif = EXIF(filename)
        return exif.extract_capture_time()

    def _read_lat_lon(self, filename):
        '''
        Use EXIF class to parse latitude and longitude from EXIF.
        '''
        exif = EXIF(filename)
        lon, lat = exif.extract_lon_lat()
        return lat, lon

    def _read_direction(self, filename):
        '''
        Use EXIF class to parse compass direction from EXIF.
        '''
        exif = EXIF(filename)
        direction = exif.extract_direction()
        return direction

    def get_file_list(self, filepath, check_exif=True):
        '''
        Get the list of JPEGs in the folder (nested folders)
        '''
        if filepath.lower().endswith(".jpg"):
            # single file
            file_list = [filepath]
        else:
            file_list = []
            for root, sub_folders, files in os.walk(self.filepath):
                if not self._is_skip(root):
                    image_files = [os.path.join(root, filename) for filename in files if (filename.lower().endswith(".jpg"))]
                    if check_exif:
                        image_files = [f for f in image_files if verify_exif(f)]
                    file_list += image_files
        return file_list

    def sort_file_list(self, file_list):
        '''
        Read capture times and sort files in time order.
        '''
        capture_times = [self._read_capture_time(filepath) for filepath in file_list]
        sorted_times_files = zip(capture_times, file_list)
        sorted_times_files.sort()
        return zip(*sorted_times_files)

    def move_groups(self, groups, sub_path=''):
        '''
        Move the files in the groups to new folders.
        '''
        for i,group in enumerate(groups):
            new_dir = os.path.join(self.filepath, sub_path, str(i))
            lib.io.mkdir_p(new_dir)
            for filepath in group:
                os.rename(filepath, os.path.join(new_dir, os.path.basename(filepath)))
            print("Moved {0} photos to {1}".format(len(group), new_dir))

    def set_skip_folders(self, folders):
        '''
        Set folders to skip when iterating through the path
        '''
        self._skip_folders = folders

    def set_file_list(self, file_list):
        '''
        Set file list for the sequence
        '''
        self.file_list = file_list

    def split(self, cutoff_distance=500., cutoff_time=None, max_sequence_length=MAXIMUM_SEQUENCE_LENGTH, move_files=True, verbose=False, skip_cutoff=False):
        '''
        Split photos into sequences in case of large distance gap or large time interval
        @params cutoff_distance: maximum distance gap in meters
        @params cutoff_time:     maximum time interval in seconds (if None, use 1.5 x median time interval in the sequence)
        '''

        file_list = self.file_list
        groups = []

        if len(file_list) >= 1:
            # sort based on EXIF capture time
            capture_times, file_list = self.sort_file_list(file_list)

            # diff in capture time
            capture_deltas = [t2-t1 for t1,t2 in zip(capture_times, capture_times[1:])]

            # read gps for ordered files
            latlons = [self._read_lat_lon(filepath) for filepath in file_list]

            # distance between consecutive images
            distances = [lib.geo.gps_distance(ll1, ll2) for ll1, ll2 in zip(latlons, latlons[1:])]

            # if cutoff time is given use that, else assume cutoff is 1.5x median time delta
            if cutoff_time is None:
                if verbose:
                    print "Cut-off time is None"
                median = sorted(capture_deltas)[len(capture_deltas)//2]
                if type(median) is not  int:
                    median = median.total_seconds()
                cutoff_time = 1.5*median

            # extract groups by cutting using cutoff time
            group = [file_list[0]]
            cut = 0
            for i,filepath in enumerate(file_list[1:]):
                cut_time = capture_deltas[i].total_seconds() > cutoff_time
                cut_distance = distances[i] > cutoff_distance
                cut_sequence_length = len(group) > max_sequence_length
                if cut_time or cut_distance or cut_sequence_length:
                    cut += 1
                    # delta too big, save current group, start new
                    groups.append(group)
                    group = [filepath]
                    if verbose:
                        if cut_distance:
                            print 'Cut {}: Delta in distance {} meters is too bigger than cutoff_distance {} meters at {}'.format(cut,distances[i], cutoff_distance, file_list[i+1])
                        elif cut_time:
                            print 'Cut {}: Delta in time {} seconds is bigger then cutoff_time {} seconds at {}'.format(cut, capture_deltas[i].total_seconds(), cutoff_time, file_list[i+1])
                        elif cut_sequence_length:
                            print 'Cut {}: Maximum sequence length {} reached at {}'.format(cut, max_sequence_length, file_list[i+1])
                else:
                    group.append(filepath)

            groups.append(group)

            # move groups to subfolders
            if move_files:
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
            latlons = [self._read_lat_lon(filepath) for filepath in file_list]

            if len(file_list)>1:
                # bearing between consecutive images
                bearings = [lib.geo.compute_bearing(ll1[0], ll1[1], ll2[0], ll2[1])
                                for ll1, ll2 in zip(latlons, latlons[1:])]
                bearings.append(bearings[-1])
                bearings = {file_list[i]: lib.geo.offset_bearing(b, offset) for i, b in enumerate(bearings)}
        elif num_file==1:
            #if there is only one file in the list, just write the direction 0 and offset
            bearings = {file_list[0]: lib.geo.offset_bearing(0.0, offset)}

        return bearings

    def remove_duplicates(self, min_distance=1e-5, min_angle=5):
        '''
        Detect duplidate photos in a folder
        @source:  a less general version of @simonmikkelsen's duplicate remover
        '''
        file_list = self.file_list

        # ordered list by time
        capture_times, file_list = self.sort_file_list(file_list)

        # read gps for ordered files
        latlons = [self._read_lat_lon(filepath) for filepath in file_list]

        # read bearing for ordered files
        bearings = [self._read_direction(filepath) for filepath in file_list]

        # interploated bearings
        interpolated_bearings = [lib.geo.compute_bearing(ll1[0], ll1[1], ll2[0], ll2[1])
                                for ll1, ll2 in zip(latlons, latlons[1:])]
        interpolated_bearings.append(bearings[-1])

        # use interploated bearings if bearing not available in EXIF
        for i, b in enumerate(bearings):
            bearings[i] = b if b is not None else interpolated_bearings[i]

        is_duplicate = False

        prev_unique = file_list[0]
        prev_latlon = latlons[0]
        prev_bearing = bearings[0]
        groups = []
        group = []
        for i, filename in enumerate(file_list[1:]):
            k = i+1
            distance = lib.geo.gps_distance(latlons[k], prev_latlon)
            if bearings[k] is not None and prev_bearing is not None:
                bearing_diff = lib.geo.diff_bearing(bearings[k], prev_bearing)
            else:
                # Not use bearing difference if no bearings are available
                bearing_diff = 360
            if distance < min_distance and bearing_diff < min_angle:
                is_duplicate = True
            else:
                prev_latlon = latlons[k]
                prev_bearing = bearings[k]

            if is_duplicate:
                group.append(filename)
            else:
                if group:
                    groups.append(group)
                group = []

            is_duplicate = False
        groups.append(group)

        # move to filepath/duplicates/group_id (TODO: uploader should skip the duplicate folder)
        self.move_groups(groups, 'duplicates')
        print("Done remove duplicate photos in {} into {} groups".format(self.filepath, len(groups)))

        return groups

