#!/usr/bin/env python
import urllib2, urllib
import json
import os
import shutil
import argparse

BASE_DIR = 'downloaded/'
# See https://www.mapillary.com/developer/api-documentation/
MAPILLARY_API_IM_SEARCH_URL = 'https://a.mapillary.com/v3/images?'
MAPILLARY_API_IM_RETRIEVE_URL = 'https://d1cuyjsrcm0gby.cloudfront.net/'
CLIENT_ID = 'TG1sUUxGQlBiYWx2V05NM0pQNUVMQTo2NTU3NTBiNTk1NzM1Y2U2'


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

    # Create URL
    params = urllib.urlencode(zip(
        ['client_id','bbox','per_page'],
        [CLIENT_ID, ','.join([str(min_lon), str(min_lat), str(max_lon), str(max_lat)]), str(max_results)]
    ))
    print(MAPILLARY_API_IM_SEARCH_URL + params)

    # Get data from server, then parse JSON
    query = urllib2.urlopen(MAPILLARY_API_IM_SEARCH_URL + params).read()
    query = json.loads(query)['features']

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
        # Use key to create url to download from and filename to save into
        key = im['properties']['key']
        url = MAPILLARY_API_IM_RETRIEVE_URL + key + '/' + im_size
        filename = key + ".jpg"

        try:
            # Get image and save to disk
            image = urllib.URLopener()
            image.retrieve(url, path + filename)

            # Log filename and GPS location
            coords = ",".join(map(str, im['geometry']['coordinates']))
            im_list.append([filename, coords])

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

    parser = argparse.ArgumentParser()
    parser.add_argument('min_lat', type=float)
    parser.add_argument('max_lat', type=float)
    parser.add_argument('min_lon', type=float)
    parser.add_argument('max_lon', type=float)
    parser.add_argument('--max_results', type=int, default=400)
    parser.add_argument('--image_size', type=int, default=1024, choices=[320,640,1024,2048])
    args = parser.parse_args()

    # query api
    query = query_search_api(args.min_lat, args.max_lat, args.min_lon, args.max_lon, args.max_results)

    # create directories for saving
    create_dirs(BASE_DIR)

    # download
    downloaded_list = download_images(query, path=BASE_DIR, size=args.image_size)

    # save filename with lat, lon
    with open(BASE_DIR+"downloaded.txt", "w") as f:
        for data in downloaded_list:
            f.write(",".join(data) + "\n")
