#!/usr/bin/env python3

import requests
import os
import shutil
import argparse

BASE_DIR = "downloaded/"
# See https://www.mapillary.com/developer/api-documentation/
MAPILLARY_API_IM_SEARCH_URL = "https://a.mapillary.com/v3/images?"
MAPILLARY_API_IM_RETRIEVE_URL = "https://images.mapillary.com"
CLIENT_ID = "MkJKbDA0bnZuZlcxeTJHTmFqN3g1dzo1YTM0NjRkM2EyZGU5MzBh"


"""
Script to download images using the Mapillary image search API.

Downloads images inside a rect (min_lat, max_lat, min_lon, max_lon).
"""


def create_dirs(base_path):
    try:
        shutil.rmtree(base_path)
    except:
        pass
    os.mkdir(base_path)


def query_search_api(min_lat, max_lat, min_lon, max_lon, max_results):
    """
    Send query to the search API and get dict with image data.
    """

    resp = requests.get(
        MAPILLARY_API_IM_SEARCH_URL,
        params={
            "client_id": CLIENT_ID,
            "bbox": ",".join([str(min_lon), str(min_lat), str(max_lon), str(max_lat)]),
            "per_page": max_results,
        },
    )
    resp.raise_for_status()
    query = resp.json()["features"]

    print("Result: {0} images in area.".format(len(query)))
    return query


def download_images(query, path, size=1024):
    """
    Download images in query result to path.

    Return list of downloaded images with lat,lon.
    There are four sizes available: 320, 640, 1024 (default), or 2048.
    """
    im_size = "thumb-{0}.jpg".format(size)
    im_list = []

    for im in query:
        # Use key to create url to download from and filename to save into
        key = im["properties"]["key"]
        url = f"{MAPILLARY_API_IM_RETRIEVE_URL}/{key}/{im_size}"
        filename = os.path.join(BASE_DIR, f"{key}.jpg")
        try:
            # Get image and save to disk
            resp = requests.get(url)
            resp.raise_for_status()
            with open(filename, "wb") as fp:
                fp.write(resp.content)
            # Log filename and GPS location
            coords = ",".join(map(str, im["geometry"]["coordinates"]))
            im_list.append([filename, coords])
        except KeyboardInterrupt:
            break
        except requests.RequestException as e:
            print("Failed to download: {} due to {}".format(filename, e))

        print("Successfully downloaded: {0}".format(filename))

    return im_list


if __name__ == "__main__":
    """
    Use from command line as below, or run query_search_api and download_images
    from your own scripts.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument("min_lat", type=float)
    parser.add_argument("max_lat", type=float)
    parser.add_argument("min_lon", type=float)
    parser.add_argument("max_lon", type=float)
    parser.add_argument("--max_results", type=int, default=400)
    parser.add_argument(
        "--image_size", type=int, default=1024, choices=[320, 640, 1024, 2048]
    )
    parser.add_argument("--output_path", default=None, required=False)
    args = parser.parse_args()

    # query api
    query = query_search_api(
        args.min_lat, args.max_lat, args.min_lon, args.max_lon, args.max_results
    )

    # create directories for saving
    if not args.output_path:
        output_path = BASE_DIR
        create_dirs(BASE_DIR)
    else:
        output_path = args.output_path
    # download
    downloaded_list = download_images(query, path=output_path, size=args.image_size)

    # save filename with lat, lon
    with open(os.path.join(output_path, "downloaded.txt"), "w") as f:
        for data in downloaded_list:
            f.write(",".join(data) + "\n")
