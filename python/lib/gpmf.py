#!/usr/bin/env python

from datetime import datetime
import struct
import binascii


'''
does the heavy lifting of parsing the GPMF format from a binary file
'''


def parse_gps(toparse, data, scale):
    gps = struct.unpack('>IIIII', toparse)

    data['gps'].append({
        'lat': float(gps[0]) / scale[0],
        'lon': float(gps[1]) / scale[1],
        'alt': float(gps[2]) / scale[3],
        'spd': float(gps[3]) / scale[3],
        's3d': float(gps[4]) / scale[4],
    })


def parse_time(toparse, data, scale):
    datetime_object = datetime.strptime(str(toparse), '%y%m%d%H%M%S.%f')
    data['time'] = datetime_object


def parse_bin(path):
    f = open(path, 'rb')

    s = {}  # the current Scale data
    output = []

    methods = {
        'GPS5': parse_gps,
        'GPSU': parse_time,
    }

    d = {'gps': []}  # up to date dictionary

    while True:
        label = f.read(4)
        if not label:  # eof
            break

        desc = f.read(4)

        # null length
        if '00' == binascii.hexlify(desc[0]):
            continue

        val_size = struct.unpack('>b', desc[1])[0]
        num_values = struct.unpack('>h', desc[2:4])[0]
        length = val_size * num_values

        # print "{} {} of size {}".format(num_values, label, val_size)

        if label == 'DVID':
            if len(d['gps']):  # first one is skipped
                output.append(d)
            d = {'gps': []}  # reset

        for i in range(num_values):
            data = f.read(val_size)

            if label in methods:
                methods[label](data, d, s)

            if label == 'SCAL':
                if 2 == val_size:
                    s[i] = struct.unpack('>h', data)[0]
                elif 4 == val_size:
                    s[i] = struct.unpack('>i', data)[0]
                else:
                    raise Exception('unknown scal size')

        # pack
        mod = length % 4
        if mod != 0:
            seek = 4 - mod
            f.read(seek)  # discarded

    return output
