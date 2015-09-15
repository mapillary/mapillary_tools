#!/usr/bin/env python
import sys
import urllib2, urllib
import json
import os
import shutil


MAPILLARY_API_IM_SEARCH_URL = 'https://a.mapillary.com/v1/im/search?'
MAX_RESULTS = 400
BASE_DIR = 'downloaded/'


'''
Script to download images using the Mapillary image search API.

Downloads images inside a rect (min_lat, max_lat, min_lon, max_lon).
'''

def create_dirs(base_path):
    try:
        shutil.rmtree(base_path)
    except:
        pass
    os.mkdir(base_path)


def query_search_api(min_lat, max_lat, min_lon, max_lon, max_results):
    '''
    Send query to the search API and get dict with image data.
    '''
    params = urllib.urlencode(zip(['min-lat', 'max-lat', 'min-lon', 'max-lon', 'max-results'],[min_lat, max_lat, min_lon, max_lon, max_results]))
    query = urllib2.urlopen(MAPILLARY_API_IM_SEARCH_URL + params).read()
    query = json.loads(query)
    print("Result: {0} images in area.".format(len(query)))
    return query


def download_images(query, path, size=1024):
    '''
    Download images in query result to path.

    Return list of downloaded images with lat,lon.
    There are four sizes available: 320, 640, 1024 (default), or 2048.
    '''
    im_size = "thumb-{0}.jpg".format(size)
    im_list = []

    for im in query:
        url = im['image_url']+im_size
        filename = im['key']+".jpg"
        try:
            image = urllib.URLopener()
            image.retrieve(url, path+filename)
            im_list.append([filename, str(im['lat']), str(im['lon'])])
            print("Successfully downloaded: {0}".format(filename))
        except KeyboardInterrupt:
            break
        except:
            print("Failed to download: {0}".format(filename))
    return im_list


if __name__ == '__main__':
    '''
    Use from command line as below, or run query_search_api and download_images
    from your own scripts.
    '''

    # handle command line parameters
    if len(sys.argv) < 5:
        sys.exit("Usage: python download_images.py min_lat max_lat min_lon max_lon [max_results](optional)")

    min_lat, max_lat, min_lon, max_lon = sys.argv[1:5]

    if len(sys.argv) == 6:
        max_results = sys.argv[5]
    else:
        max_results = MAX_RESULTS

    # query api
    query = query_search_api(min_lat, max_lat, min_lon, max_lon, max_results)

    # create directories for saving
    create_dirs(BASE_DIR)

    # download
    downloaded_list = download_images(query, path=BASE_DIR)

    # save filename with lat, lon
    with open(BASE_DIR+"downloaded.txt", "w") as f:
        for data in downloaded_list:
            f.write(",".join(data) + "\n")
