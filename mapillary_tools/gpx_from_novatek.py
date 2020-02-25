#!/usr/bin/env python
#
# Novatek gps data struct and decode: Sergei Franco (sergei at sergei.nz)
# License: GPL3
# 
# changed M_Solodzhuk
import os
import struct
import sys
from datetime import datetime
from geo import write_gpx

HEADER = 8

def fix_coordinates(hemisphere,coordinate):
    # Novatek stores coordinates in odd DDDmm.mmmm format
    minutes = coordinate % 100.0
    degrees = coordinate - minutes
    coordinate = degrees / 100.0 + (minutes / 60.0)
    if hemisphere in 'SW':
        return -1*float(coordinate)
    else:
        return float(coordinate)


def get_gps_atom(atom_pos, atom_size, f):
    f.seek(atom_pos)
    data = f.read(atom_size)

    expected_type = 'free'
    expected_magic = 'GPS '
    atom_size1, atom_type, magic = struct.unpack_from('>I4s4s',data)

    try:
        atom_type = atom_type.decode()
        magic = magic.decode()
        #sanity:
        if atom_size != atom_size1 or atom_type != expected_type or magic != expected_magic:
            raise IOError("Error! skipping atom at %x (expected size:%d, actual size:%d, expected type:%s, actual type:%s, expected magic:%s, actual maigc:%s)!" %
                  (int(atom_pos),atom_size,atom_size1,expected_type,atom_type,expected_magic,magic))
            

    except UnicodeDecodeError as e:
        raise IOError("Skipping: garbage atom type or magic. Error: %s." % str(e))
        

    # checking for weird Azdome 0xAA XOR "encrypted" GPS data. This portion is a quick fix.
    if ord(data[12]) == 0x05:          #in python27 data - str in python3 bytes
        # XOR decryptor
        s = ''.join([chr(ord(c)^0xAA) for c in data[26:128]])

        date_time = datetime.strptime(s[:14],'%Y%m%d%H%M%S')
              
        lat = float(s[31:33]) + float(s[33:35] + '.' + s[35:39]) / 60
        if s[30] == 'S':
            lat *= -1
        lon = float(s[40:43]) + float(s[43:45] + '.' +s[45:49]) / 60
        if s[39] == 'W':
            lon *= -1

        speed = float(s[49:57])/3.6
        #no bearing data
        bearing = 0
        ele = 0

    else:

        # Added Bearing as per RetiredTechie contribuition: http://retiredtechie.fitchfamily.org/2018/05/13/dashcam-openstreetmap-mapping/
        hour, minute, second, year, month, day = struct.unpack_from('<IIIIII',data, 16)
        active, latitude_b, longitude_b, __ = struct.unpack_from('<ssss',data, 40)
        latitude,longitude,speed,bearing = struct.unpack_from('<IIIIIIssssffff',data, 44)

        try:
            active = active.decode()
            latitude_b = latitude_b.decode()
            longitude_b = longitude_b.decode()

        except UnicodeDecodeError as e:
            raise IOError("Skipping: garbage data. Error: %s." % str(e))
            return

        #time = fix_time(hour,minute,second,year,month,day)
        time = "{:4d}{:02d}{:02d}{:02d}{:02d}{:02d}".format((year+2000),month,day,hour,minute,second)
        date_time = datetime.strptime(time,'%Y%m%d%H%M%S')
        lat = fix_coordinates(latitude_b,latitude)
        lon = fix_coordinates(longitude_b,longitude)
        speed *= 0.514444
        ele = 0

        #it seems that A indicate reception
        if active != 'A':
            print("Skipping: lost GPS satelite reception. Time: %s." % time)
            return

    return (date_time, lat,lon,ele, 0.0, speed,bearing)

def process_file(in_file):
    points = []
    #print("Processing file '%s'..." % in_file)
    with open(in_file, "rb") as f:
        offset = 0
        while True:
            atom_pos = f.tell()
            hdr = f.read(HEADER)
            if not hdr:
                break      
            atom_size, atom_type = struct.unpack('>I4s',hdr)
            
            if atom_type == 'moov':
                #print("Found moov atom...")
                sub_offset = offset + HEADER             #sub_offset = f.tell()

                while sub_offset < (offset + atom_size):
                    hdr = f.read(HEADER)
                    sub_atom_size, sub_atom_type = struct.unpack('>I4s',hdr)

                    if sub_atom_type == 'gps ':
                        #print("Found gps chunk descriptor atom...")
                        gps_offset = 16 + sub_offset # +16 = skip headers
                        f.seek(gps_offset,0)
                        while gps_offset < ( sub_offset + sub_atom_size):
                            hdr = f.read(HEADER)
                            a_pos,a_size = struct.unpack('>II',hdr)
                            if not a_pos or not a_size:
                                continue
                            points.append(get_gps_atom(a_pos, a_size,f))
                            gps_offset += HEADER
                            f.seek(gps_offset,0)

                    sub_offset += sub_atom_size
                    f.seek(sub_offset,0)

            offset += atom_size
            f.seek(offset,0)

    return points

def gpx_from_novatek(novatek_video):

    gps_data = process_file(novatek_video)

    basename, __ = os.path.splitext(novatek_video)
    gpx_path = basename + '.gpx'

    write_gpx(gpx_path, sorted(gps_data))

    return gpx_path