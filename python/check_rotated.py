#!/usr/bin/env python3
'''
This looks at a sequence owned by a specified user,
and finds images which may be rotated incorrectly
Use from command line as below.

'''

import argparse
import sys
from io import BytesIO
import getpass
import requests
import exifread

BASE_DIR = 'downloaded/'
# See https://www.mapillary.com/developer/api-documentation/
MAPILLARY_API_SEQ_URL = 'https://a.mapillary.com/v3/sequences/'
CLIENT_ID = 'TG1sUUxGQlBiYWx2V05NM0pQNUVMQTo2NTU3NTBiNTk1NzM1Y2U2'
CLIENT_ID_IMAGE = 'MkJKbDA0bnZuZlcxeTJHTmFqN3g1dzo1YTM0NjRkM2EyZGU5MzBh'
MAPILLARY_API_IM_RETRIEVE_URL = 'https://d1cuyjsrcm0gby.cloudfront.net/'
MAPILLARY_LOGIN_URL = 'https://a.mapillary.com/v2/ua/login'
MAPILLARY_GET_ORIG_IMAGE_URL = 'https://a.mapillary.com/v3/model.json'

'''
Script to download images using the Mapillary image search API.

Downloads images inside a rect (min_lat, max_lat, min_lon, max_lon).
'''

def query_seq_api(seq_id):
    '''
    Send query to the seq API and get images
    '''

    # Create URL
    payload = {'client_id': CLIENT_ID}
    req = requests.get(MAPILLARY_API_SEQ_URL + seq_id, params=payload)
    if req.status_code != 200:
        print("Failed to retrieve sequence, status: ", req.status_code)
        sys.exit(1)

    # Get data from server, then parse JSON
    image_keys = req.json()['properties']['coordinateProperties']['image_keys']

    print("Result: {0} images in sequence.".format(len(image_keys)))

    return image_keys


def get_original_image_orientation(session, headers_image, image_key):
    '''
    Returns request containing original image
'''
    paths_value = '[["imageByKey","{:s}",["key","original_url"]],["blursByImageKey","{:s}",["applied","pending"],["blur","key","state","user"]]]'.format(image_key, image_key)
    payload_image = {'client_id': CLIENT_ID_IMAGE, 'paths': paths_value, 'method': 'get'}
    req = session.get(MAPILLARY_GET_ORIG_IMAGE_URL, params=payload_image, headers=headers_image)
    if req.status_code != 200:
        print("Failed to get image info for ", image_key, "; status code: ", req.status_code)
        return None
    orig_url = req.json()['jsonGraph']['imageByKey'][image_key]['original_url']['value']
    req_orig = session.get(orig_url, stream=True)
    if req_orig.status_code != 200:
        return None

    chunk = req_orig.iter_content(chunk_size=64 * 1024) # exif is limited to 64K
    tags = next(chunk)
    tags = exifread.process_file(BytesIO(tags),
                                 details=False, stop_tag='Image Orientation')
    if not 'Image Orientation' in tags:
        print('Image ', image_key, ' does not have "Image Orientation"')
        return None
    orientation = tags['Image Orientation']
    return orientation


def check_orientation(images, email, password):
    '''
    Check orientation of images

    Print orientation of first image
    and print all image ids which have different orientation
    '''

    if not images:
        return 0

    session = requests.Session()
    payload = {'client_id': CLIENT_ID_IMAGE}
    headers_login = {'Referer': 'https://www.mapillary.com/app/'}
    req_login = session.post(MAPILLARY_LOGIN_URL, params=payload,
                             data={'email': email, 'password': password},
                             headers=headers_login)

    if req_login.status_code != 200:
        print("Login failed")
        sys.exit(1)

    headers_image = {'Authorization': 'Bearer ' + req_login.json()['token'],
                     'Referer': 'https://www.mapillary.com/app/&username'}
    key = images[0]
    orientation = get_original_image_orientation(session, headers_image, key)
    if orientation is None:
        print('First image ', key, ' does not have "Image Orientation"')
        return 0
    print('First image orientation: ', orientation)
    im_number = 0
    im_mismatch = 0
    for key in images[1:]:
        current_orientation = get_original_image_orientation(session, headers_image, key)
        im_number += 1
        if current_orientation is None:
            print(key, ' no orientation found')
        elif orientation.values[0] != current_orientation.values[0]:
            im_mismatch += 1
            print(key, ' mismatch: current: ', current_orientation,
                  ' does not match first: ', orientation)
    return im_mismatch


if __name__ == '__main__':

    PARSER = argparse.ArgumentParser(description='Examine sequence for images which are flipped.'
                                     ' Looks at original uploaded images, '
                                     'so must enter user''s password from terminal')
    PARSER.add_argument('seq_id', type=str,
                        help='Sequence id')
    PARSER.add_argument('email', type=str,
                        help='Mapillary user''s email')
    PARSER.add_argument('--password', type=str,
                        help='Mapillary user''s password, not secure, '
                        'if this argument does not exist, password will be prompted from terminal.'
                        ' It is more secure to skip this argument.')
    ARGS = PARSER.parse_args()

    PASSWORD = ''
    if ARGS.password:
        PASSWORD = ARGS.password
    else:
        PASSWORD = getpass.getpass('Enter password for '  + ARGS.email + ': ')
    # query api
    IMAGES_SEQ = query_seq_api(ARGS.seq_id)

    MISMATCHED = check_orientation(IMAGES_SEQ, ARGS.email, PASSWORD)
    print(MISMATCHED, ' images have different orientation than first image')
