#!/usr/bin/env python

import json
import re
import os

def get_args():
    import argparse
    p = argparse.ArgumentParser(description='Convert Mapillary ios json format to gpx.')
    p.add_argument('path', help='Path to folder of json files.')
    return p.parse_args()

if __name__ == '__main__':
    args = get_args()

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
                gpx += "<trkpt lat=\"" + str(data['MAPLatitude']) + "\" lon=\"" + str(data['MAPLongitude']) + "\">"
                gpx += "<ele>" + str(data['MAPAltitude']) + "</ele>"
                gpx += "<time>" + t + "</time>"
                gpx += "</trkpt>"

    gpx += "</trkseg>"
    gpx += "</trk>"
    gpx += "</gpx>"

    print gpx