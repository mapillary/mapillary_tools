#!/usr/bin/env python

"""
Script to export Panoramio photos for a user
    - Download meta data from panoramio API
    - Download geotagged photos
    - Organize photos into sequences
    - Add Mapillary tags

NOTE: Use only with permissions from the original authors of the photos in Panoramio
"""

import argparse
import urllib2, urllib
import json
import os
import datetime
import uuid
import shutil

from lib import io
from lib import uploader
from lib import sequence
from lib.exifedit import ExifEdit
from lib.exifedit import create_mapillary_description
from lib.exif import EXIF


def api_url(user_id, from_id, to_id, size):
    return ("http://www.panoramio.com/map/get_panoramas.php?" +
            "set={}" +
            "&from={}&to={}&" +
            "minx=-180&miny=-90&maxx=180&maxy=90&&mapfilter=false&" +
            "size={}").format(user_id, from_id, to_id, size)


def download_metadata(user_id, size="original"):
    """Download basic meta data for a user from API.

    NOTE: Only geotagged photos are returned from API
    """
    image_per_call = 100
    has_more = True
    meta = {"photos": []}
    page = 0
    num_photos = 0
    while has_more:
        url = api_url(user_id,
                      page * image_per_call,
                      (page+1) * image_per_call,
                      size)
        r = json.loads(urllib2.urlopen(url).read())
        meta["photos"] += r["photos"]
        has_more = r["has_more"]
        page += 1
        num_photos += len(r["photos"])
    meta["count"] = len(meta["photos"])
    return meta


def download_photos(meta, image_path):
    """Download photos given export metadata."""
    photos = meta["photos"]
    num_photo = len(photos)
    photo_files = []
    for i, p in enumerate(photos):
        io.progress(i + 1, num_photo, "{}/{}".format(i + 1, num_photo))
        url = p["photo_file_url"]
        photo_file = download_path(image_path, p["photo_id"])
        if not os.path.isfile(photo_file):
            urllib.urlretrieve(url, photo_file)
        meta["photos"][i]["photo_file_path"] = photo_file
        photo_files.append("{}.jpg".format(p["photo_id"]))

    with open(download_done_file(image_path), "wb") as f:
        f.write("\n".join(photo_files))
    return photo_files

def download_path(image_path, photo_id):
    return os.path.join(image_path, "{}.jpg".format(photo_id))

def download_done_file(image_path):
    return os.path.join(image_path, "DOWNLOAD_DONE")

def processing_done_file(image_path):
    return os.path.join(image_path, "PROCESSING_DONE")

def get_args():
    p = argparse.ArgumentParser(description='Export Panoramio photos for a user')
    p.add_argument("user_id", help='Panoramio user id')
    p.add_argument("data_path", help="Path to save image and meta data")
    p.add_argument("--user", help="Mapillary user name")
    p.add_argument("--email", help="Mapillary user email")
    p.add_argument('--size', help='Image size (medium, original, small)', default="original")
    return p.parse_args()


if __name__ == "__main__":

    args = get_args()
    user_id = args.user_id
    size = args.size

    data_path = os.path.join(args.data_path, user_id)
    image_path = os.path.join(data_path, size)
    io.mkdir_p(image_path)

    meta_file = os.path.join(data_path, "meta.json")


    # Prepare meta data
    if os.path.isfile(meta_file) is False:
        # Download meta data
        print "Downloading meta data from Panoramio API ..."
        meta = download_metadata(user_id, size)
        with open(meta_file, "wb") as f:
            f.write(json.dumps(meta, indent=4))
    else:
        # load meta data
        with open(meta_file, "rb") as f:
            meta = json.loads(f.read())

    # Download photos
    if not os.path.exists(download_done_file(image_path)):
        print("Downloading photos ...")
        photos = download_photos(meta, image_path)
    else:
        for i, m in enumerate(meta["photos"]):
            meta["photos"][i]["photo_file_path"] = download_path(image_path, m["photo_id"])


    # Handle EXIF errors
    num_missing_date = 0
    num_exif_error = 0
    failed_folder = os.path.join(data_path, "failed")
    io.mkdir_p(failed_folder)
    valid_files = []

    print("\nAdding GPS ...")
    # Add GPS positions
    for i, p in enumerate(meta["photos"]):

        photo_file = p["photo_file_path"]

        if os.path.isfile(photo_file):
            exif = EXIF(photo_file)
            try:
                exif = EXIF(photo_file)
            except Exception as e:
                print "EXIF read error '{}' for image {}. Skipping".format(e, photo_file)
                shutil.move(photo_file, os.path.join(failed_folder, os.path.basename(photo_file)))
                num_exif_error += 1
                continue

            try:
                capture_time = exif.extract_capture_time()
            except Exception as e:
                print "Datetime error '{}' for image {}. Skipping".format(e, photo_file)
                shutil.move(photo_file, os.path.join(failed_folder, os.path.basename(photo_file)))
                num_exif_error += 1
                continue

            if capture_time == 0:
                # Use upload time + 12:00:00 instead
                upload_time = p["upload_date"] + " 12:00:00"
                capture_time = datetime.datetime.strptime(upload_time, "%d %B %Y %H:%M:%S")
                print("Image {} missing time stamp. Using update date instead.".format(photo_file))
                num_missing_date += 1

            exifedit = ExifEdit(photo_file)
            exifedit.add_lat_lon(p["latitude"], p["longitude"])
            exifedit.add_altitude(p.get("altitude", 0))
            exifedit.add_date_time_original(capture_time)
            exifedit.write()
            valid_files.append(photo_file)

    # Sequence Cut
    s = sequence.Sequence(image_path, skip_subfolders=True)
    sequences = s.split(move_files=False, cutoff_distance=100)
    sequence_ids = {}
    for s in sequences:
        sequence_uuid = str(uuid.uuid4())
        for im in s:
            sequence_ids[im] = sequence_uuid

    # Get authentication info
    email, upload_token, secret_hash, upload_url = uploader.get_full_authentication_info(email=args.email)

    # Encode Mapillary meta
    print("Adding Mapillary tags ...")
    for p in meta["photos"]:
        photo_file = p["photo_file_path"]
        if photo_file in sequence_ids:
            external_properties = {
                "photo_id": p["photo_id"]
            }
            create_mapillary_description(
                photo_file, args.user, email,
                upload_token, sequence_ids[photo_file],
                secret_hash=secret_hash,
                external_properties=external_properties,
                verbose=False
            )

    print "".join(['\nExport completed:' +
          '\nPhotos with no timestamp : {}'.format(num_missing_date),
          '\nPhotos with exif error : {}'.format(num_exif_error),
          '\nYou can now review your photos at "{}".'.format(image_path) +
          '\nMove the photos you want to skip to another folder.' +
          '\nUpload the photos by running "python upload.py {}"'.format(image_path)])