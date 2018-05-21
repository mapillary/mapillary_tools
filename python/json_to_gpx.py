#!/usr/bin/env python

import json
import re
import os

def get_args():
    import argparse
    p = argparse.ArgumentParser(description = 'Convert Mapillary ios json format to gpx.')
    p.add_argument('path', help = 'Path to folder of json files.')
    p.add_argument('-o', '--out_path', help = 'path to where the gpx trace should be stored', required = False, default = ".")
    p.add_argument('-g', '--gpx_trace_name', help = 'name for the gpx trace', required = False, default = None)
    return p.parse_args()

if __name__ == '__main__':
    args = get_args()

    if args.gpx_trace_name == None:
        gpx_full_file_name = os.path.join(args.out_path, os.path.basename(args.path) + ".gpx")
    else:
        gpx_full_file_name = os.path.join(args.out_path, args.gpx_trace_name + ".gpx")

    gpx = "<gpx>"
    gpx += "<trk>"
    gpx += "<name>IOS JSON to GPX</name>"
    gpx += "<trkseg>"

    pattern = re.compile("^(\d*)_(\d*)_(\d*)_(\d*)_(\d*)_(\d*)_*")

    for fn in os.listdir(args.path):
        filename = args.path + "/" + fn
        t = fn[:-5]

        if t == "history":
            continue

        match = pattern.match(t)

        year = match.group(1)
        month = match.group(2)
        day = match.group(3)
        hour = match.group(4)
        minute = match.group(5)
        second = match.group(6)

        t = "{}-{}-{}T{}:{}:{}Z".format(year, month, day, hour, minute, second)

        if os.path.isfile(filename):
            with open(filename, "r") as f:
                data = json.load(f)
                if ('MAPLatitude' in data) and ('MAPLongitude' in data):
                    gpx += "<trkpt lat=\"" + str(data['MAPLatitude']) + "\" lon=\"" + str(data['MAPLongitude']) + "\">"
                    if 'MAPAltitude' in data:
                        gpx += "<ele>" + str(data['MAPAltitude']) + "</ele>"
                    gpx += "<time>" + t + "</time>"
                    gpx += "</trkpt>"

    gpx += "</trkseg>"
    gpx += "</trk>"
    gpx += "</gpx>"

    with open(gpx_full_file_name, "w") as f:
        f.write(gpx)
