#!/usr/bin/env python

import datetime
import struct
import binascii

# author https://github.com/stilldavid

'''
does the heavy lifting of parsing the GPMF format from a binary file
'''


def parse_gps(toparse, data, scale):
    gps = struct.unpack('>lllll', toparse)

    data['gps'].append({
        'lat': float(gps[0]) / scale[0],
        'lon': float(gps[1]) / scale[1],
        'alt': float(gps[2]) / scale[3],
        'spd': float(gps[3]) / scale[3],
        's3d': float(gps[4]) / scale[4],
    })


def parse_time(toparse, data, scale):
    datetime_object = datetime.datetime.strptime(
        str(toparse), '%y%m%d%H%M%S.%f')
    data['time'] = datetime_object


def parse_accl(toparse, data, scale):
    # todo: fusion
    if 6 == len(toparse):
        data['accl'] = struct.unpack('>hhh', toparse)


def parse_gyro(toparse, data, scale):
    # todo: fusion
    if 6 == len(toparse):
        data['gyro'] = struct.unpack('>hhh', toparse)


def parse_fix(toparse, data, scale):
    data['gps_fix'] = struct.unpack('>I', toparse)[0]


def parse_precision(toparse, data, scale):
    data['gps_precision'] = struct.unpack('>H', toparse)[0]


'''
since we only get 1Hz timestamps and ~18Hz GPS, interpolate timestamps
in between known good times.

Sometimes it's 18Hz, sometimes 19Hz, so peek at the next row and grab their
timestamp. On the last one, just add 1 second as a best guess, worst case it's
off by ~50 milliseconds
'''


def interpolate_times(frame, until):
    tot = len(frame['gps'])
    diff = until - frame['time']
    offset = diff / tot

    for i, row in enumerate(frame['gps']):
        toadd = datetime.timedelta(microseconds=(offset.microseconds * i))
        frame['gps'][i]['time'] = frame['time'] + toadd


def parse_bin(path):
    f = open(path, 'rb')

    s = {}  # the current Scale data to apply to next requester
    output = []

    # handlers for various fourCC codes
    methods = {
        'GPS5': parse_gps,
        'GPSU': parse_time,
        'GPSF': parse_fix,
        'GPSP': parse_precision,
        'ACCL': parse_accl,
        'GYRO': parse_gyro,
    }

    d = {'gps': []}  # up to date dictionary, iterate and fill then flush

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

        # print "{} {} of size {} and type {}".format(num_values, label,
        # val_size, desc[0])

        if label == 'DVID':
            if len(d['gps']):  # first one is empty
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
