import sys
import urllib2, urllib
import json
import os
import shutil
import socket
import time
from datetime import timedelta

'''
this scripts is a fast way to download all your GPS traces from
the sequences uploaded to mapillary.
and you could do what you want with yours GPS traces. :)

Script to download images using the Mapillary image search API.

by danilo@lacosox.org based on download_images.py
14/10/2015 

ex: python download_gpx_from_sequences.py min_lat max_lat min_lon max_lon [max_results] [filter_by_user_name]

'''


MAPILLARY_API_IM_SEARCH_URL = 'https://a.mapillary.com/v2/search/s/ul?'
MAPILLARY_PATH_GPX_URL = 'https://a.mapillary.com/v1/s/gpx/'
MIN_LAT_G = -90
MAX_LAT_G = 90
MIN_LON_G = -180
MAX_LON_G = 180
MAX_RESULTS = 2
BASE_DIR = 'gpx_from_sequences/'
USER_FILTER=''

#I create a new aplication for get this client_id.
CLIENT_ID = 'dTBiWGgweEdleXJhVVBmOFNfVVRxZzpkYThkNzBkYTI3ZGNhMGI1'

START_TIME = time.time()
LOG_FILE = "downloaded_"+format(START_TIME)+".txt"
MAX_ATTEMPTS = 10

def create_dirs(base_path):
    if not os.path.exists(base_path):
        os.mkdir(base_path)
    

def query_search_api(client_id,min_lat, max_lat, min_lon, max_lon, max_results, user_filter):
    '''
    Send query to the search API and get dict with image data.
    '''
    if user_filter:
        params = urllib.urlencode(zip(['client_id','min-lat', 'max-lat', 'min-lon', 'max-lon', 'limit', 'user'],[client_id, min_lat, max_lat, min_lon, max_lon, max_results, user_filter]))
    else:
        params = urllib.urlencode(zip(['client_id','min-lat', 'max-lat', 'min-lon', 'max-lon', 'limit'],[client_id, min_lat, max_lat, min_lon, max_lon, max_results]))
        
#    print params
    query = urllib2.urlopen(MAPILLARY_API_IM_SEARCH_URL + params).read()
    query = json.loads(query)
    print("Result: {0} sequences in area.".format(len(query['ss'])))
    return query


def download_gpx(query, path):
    '''
    Download files in query result to path.

    Return list of downloaded  with lat,lon.
   
    '''
    im_list = []
    counter = 0
    
    for im in query['ss']:
        filename = im['key']+".gpx"
        url = MAPILLARY_PATH_GPX_URL + filename
        retry_counter=0
        
        for attempt in range(MAX_ATTEMPTS):
            try:
                image = urllib.URLopener()
                image.retrieve(url, path+filename)
                im_list.append([filename, str(im['captured_at']),str(im['user']), str(im['location'])])
                counter = counter+1
                print("Successfully downloaded: {0} {1}/{2}".format(filename,counter,len(query['ss'])))
                break
            except (KeyboardInterrupt, SystemExit):
                sys.exit()
            except:
                retry_counter = retry_counter+1
                if retry_counter >= MAX_ATTEMPTS:
                        print("Finally Failed: {0}".format(filename))
                else:
                        print("Failed to download (retrying {0}/{1}): {2}".format(retry_counter,MAX_ATTEMPTS,filename))
            
                  
    return im_list


if __name__ == '__main__':
    '''
    Use from command line as below
    '''

    # handle command line parameters
    try:
        min_lat, max_lat, min_lon, max_lon = sys.argv[1:5]
    except:
        sys.exit("Usage: %s min_lat max_lat min_lon max_lon [max_results] [user_name]" % sys.argv[0])

    if len(sys.argv)>=6:
        max_results = sys.argv[5]
    else:
        max_results = MAX_RESULTS
        print("Warning: default max_results=%d" % MAX_RESULTS)

    if len(sys.argv)>=7:
        user_filter = sys.argv[6]
    else:
        user_filter = USER_FILTER
        print("Warning: USER NOT SPECIFIED - NOT A GOOD IDEA, trying to list last gpx from all users")
        
    # query api
    print("Getting the files list...")
    query = query_search_api(CLIENT_ID, min_lat, max_lat, min_lon, max_lon, max_results, user_filter)

    # create directories for saving
    create_dirs(BASE_DIR)

    # download
    print("Log file at %s" % BASE_DIR+LOG_FILE)
    
    downloaded_list = download_gpx(query, path=BASE_DIR)

    # save filename with lat, lon
    with open(BASE_DIR+LOG_FILE, "w") as f:
        for data in downloaded_list:
            f.write(",".join(data) + "\n")
