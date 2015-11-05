import sys
import urllib2, urllib
import json
import os
import shutil
import socket
import time
import datetime
from datetime import timedelta
import argparse

'''
this scripts is a fast way to download all your GPS traces from
the sequences uploaded to mapillary.
and you could do what you want with yours GPS traces. :)

Script to download images using the Mapillary image search API.

by danilo@lacosox.org based on download_images.py
14/10/2015 

usage: download_gpx_from_sequences.py [-h]
                                      [-r min_lat max_lat min_lon max_long]
                                      [-m MAXRESULTS] [-u USERNAME]
                                      [-d1 STARTDATE] [-d2 ENDDATE]
ranges:
========

min_lat = -90 to 90
max_lat = -90 to 90
min_lon = -180 to 180
max_lon = -180 to 180
maxresults = numeric >= 0
filter_by_user_name = string
Limit_Start_Date = a date informat YYYMMDD ex:20150101 default hour: 00:00
Limit_End_Date = a date informat YYYMMDD ex:20151231 default hour: 23:59

'''

MAPILLARY_API_IM_SEARCH_URL = 'https://a.mapillary.com/v2/search/s/ul?'
MAPILLARY_PATH_GPX_URL = 'https://a.mapillary.com/v1/s/gpx/'
MIN_LAT_G = -90
MAX_LAT_G = 90
MIN_LON_G = -180
MAX_LON_G = 180
MAX_RESULTS = 10 #default value only for test, please specify your limit
BASE_DIR = 'gpx_from_sequences/'
USER_FILTER=''
DEFAULT_START_TIME = '20000101' #2000-01-01 
DEFAULT_END_TIME =  '21001231' #2100-12-31

#I create a new aplication for get this client_id.
#CLIENT_ID = 'dTBiWGgweEdleXJhVVBmOFNfVVRxZzpkYThkNzBkYTI3ZGNhMGI1'

#default Mapillary web client ID, only for test, may you need create a new application and get a new id to replace it
# i'm not sure if a good idea use this ID
CLIENT_ID = 'MkJKbDA0bnZuZlcxeTJHTmFqN3g1dzo1YTM0NjRkM2EyZGU5MzBh'

START_TIME = time.time()
LOG_FILE = "downloaded_"+time.strftime("%Y%m%d",time.localtime(START_TIME))+".txt"
MAX_ATTEMPTS = 10
START_ESTIMATED_TIME_AFTER = 2 #start calc estimated time after this count.

def create_dirs(base_path):
    if not os.path.exists(base_path):
        os.mkdir(base_path)
    
#is better with a log :)
def write_log(line):
    with open(BASE_DIR+LOG_FILE, "a") as f:
            f.write(line + "\n")
    f.close


def query_search_api(client_id,min_lat, max_lat, min_lon, max_lon, max_results, user_filter, limit_start_time, limit_end_time):
    '''
    Send query to the search API and get dict with image data.
    '''
    if user_filter:
        params = urllib.urlencode(zip(['client_id','min_lat', 'max_lat', 'min_lon', 'max_lon', 'limit',     'user',      'start_time',     'end_time'],\
				      [client_id,   min_lat,   max_lat,   min_lon,   max_lon,   max_results, user_filter, limit_start_time, limit_end_time]))
    else:
        params = urllib.urlencode(zip(['client_id','min_lat', 'max_lat', 'min_lon', 'max_lon', 'limit'     , 'start_time',     'end_time'],\
				      [client_id,   min_lat,   max_lat,   min_lon,   max_lon,   max_results, limit_start_time, limit_end_time]))
        
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
	file_captured_at=datetime.datetime.fromtimestamp(int(int(im['captured_at'])/1000)).strftime('%Y%m%d')
        retry_counter=0
        counter = counter+1
        
        for attempt in range(MAX_ATTEMPTS):
            try:
                
                image = urllib.URLopener()
                image.retrieve(url, path+file_captured_at+'_'+filename)
                write_log(file_captured_at+'_'+filename+','+str(im['captured_at'])+','+str(im['user'])+','+str(im['location']))
                
		if START_ESTIMATED_TIME_AFTER >=  counter:
                        estimated_time = '...'
                else:
                        elapsed_time = time.time() - START_TIME
                        estimated_time = str(timedelta(seconds=(elapsed_time/counter)*(len(query['ss'])-counter))).split(".")[0]

                print("Successfully downloaded: {0} {1}/{2} ET {3}".format(file_captured_at+'_'+filename,counter,len(query['ss']),estimated_time))
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

def error_exit(extra_txt=''):

	if len(extra_txt)>0:
		print("Warning:%s" % extra_txt)

	sys.exit("Usage: %s min_lat max_lat min_lon max_lon [max_results] [user_name] [start_time] [end_time]" % sys.argv[0])



if __name__ == '__main__':
    '''
    Use from command line as below
    '''

    parser = argparse.ArgumentParser(description='Download GPS Traces from Mapillary.',formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-r','--rect', nargs=4,metavar=('min_lat', 'max_lat', 'min_lon','max_long'),
                              default=[-90, 90, -180, 180], help='latitude and longitude rectangle')
    parser.add_argument('-m','--maxresults' , type=int, default=MAX_RESULTS, help='Max results to get from server')
    parser.add_argument('-u','--username'   , default='', help='Get traces only from user.')
    parser.add_argument('-d1','--startdate' , type=int, default=DEFAULT_START_TIME, help='Get traces only from this date. YYYYMMDD')
    parser.add_argument('-d2','--enddate'   , type=int, default=DEFAULT_END_TIME,   help='Get traces until this date only. YYYYMMDD')

    args = parser.parse_args()
    
    min_lat = args.rect[0]
    max_lat = args.rect[1]
    min_lon = args.rect[2]
    max_lon = args.rect[3]
    max_results = args.maxresults

    if max_results == MAX_RESULTS:
        print("Warning: default max_results=%d" % MAX_RESULTS)

    if args.username != '':
        user_filter = args.username
    else:
        user_filter = USER_FILTER
        print("Warning: USER NOT SPECIFIED - NOT A GOOD IDEA, trying to list last gpx from all users")

    #validate and set de start_time        
    limit_start_time = str(args.startdate)
    if limit_start_time.isdigit() and \
       int(limit_start_time[4:6])>=1 and \
       int(limit_start_time[4:6])<=12 and \
       int(limit_start_time[6:8])>=1 and \
       int(limit_start_time[6:8])<=31:
          limit_start_time = int(datetime.datetime(int(limit_start_time[:4]),int(limit_start_time[4:6]),int(limit_start_time[6:8]),0,0).strftime('%s')) * 1000
    else:
	  error_exit("star_time bad defined")

    #validate and set de end_time        
    limit_end_time = str(args.enddate)

    if limit_end_time.isdigit() and \
       int(limit_end_time[4:6])>=1 and \
       int(limit_end_time[4:6])<=12 and \
       int(limit_end_time[6:8])>=1 and \
       int(limit_end_time[6:8])<=31:
	  limit_end_time = int(datetime.datetime(int(limit_end_time[:4]),int(limit_end_time[4:6]),int(limit_end_time[6:8]),23,59).strftime('%s')) * 1000
    else:
	  error_exit("end_time bad defined")


    # query api
    print("Getting the files list...")
    query = query_search_api(CLIENT_ID, min_lat, max_lat, min_lon, max_lon, max_results, user_filter, limit_start_time, limit_end_time)

    # create directories for saving
    create_dirs(BASE_DIR)

    # download
    print("Log file at %s" % BASE_DIR+LOG_FILE)
    
    downloaded_list = download_gpx(query, path=BASE_DIR)
