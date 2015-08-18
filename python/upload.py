#!/usr/bin/python

import sys
import urllib2, urllib
import socket
import os
import base64
import mimetypes
import random
import string
from Queue import Queue
import threading
import exifread
import time

'''
Script for uploading images taken with the Mapillary
iOS or Android apps.

Intended use is for cases when you have multiple SD cards
or for other reasons have copied the files to a computer
and you want to bulk upload.

Requires exifread, run "pip install exifread" first
(or use your favorite installer).

NB: DO NOT USE THIS ON OTHER IMAGE FILES THAN THOSE FROM
THE MAPILLARY APPS, WITHOUT PROPER TOKENS IN EXIF, UPLOADED
FILES WILL BE IGNORED SERVER-SIDE.
'''

MAPILLARY_UPLOAD_URL = "https://d22zcsn13kp53w.cloudfront.net/"
PERMISSION_HASH = "eyJleHBpcmF0aW9uIjoiMjAyMC0wMS0wMVQwMDowMDowMFoiLCJjb25kaXRpb25zIjpbeyJidWNrZXQiOiJtYXBpbGxhcnkudXBsb2Fkcy5pbWFnZXMifSxbInN0YXJ0cy13aXRoIiwiJGtleSIsIiJdLHsiYWNsIjoicHJpdmF0ZSJ9LFsic3RhcnRzLXdpdGgiLCIkQ29udGVudC1UeXBlIiwiIl0sWyJjb250ZW50LWxlbmd0aC1yYW5nZSIsMCwyMDQ4NTc2MF1dfQ=="
SIGNATURE_HASH = "f6MHj3JdEq8xQ/CmxOOS7LvMxoI="
BOUNDARY_CHARS = string.digits + string.ascii_letters
NUMBER_THREADS = int(os.getenv('NUMBER_THREADS', '4'))
MAX_ATTEMPTS = int(os.getenv('MAX_ATTEMPTS', '10'))
UPLOAD_PARAMS = {"url": MAPILLARY_UPLOAD_URL, "permission": PERMISSION_HASH, "signature": SIGNATURE_HASH, "move_files":True}


def encode_multipart(fields, files, boundary=None):
    """
    Encode dict of form fields and dict of files as multipart/form-data.
    Return tuple of (body_string, headers_dict). Each value in files is a dict
    with required keys 'filename' and 'content', and optional 'mimetype' (if
    not specified, tries to guess mime type or uses 'application/octet-stream').

    From MIT licensed recipe at
    http://code.activestate.com/recipes/578668-encode-multipart-form-data-for-uploading-files-via/
    """
    def escape_quote(s):
        return s.replace('"', '\\"')

    if boundary is None:
        boundary = ''.join(random.choice(BOUNDARY_CHARS) for i in range(30))
    lines = []

    for name, value in fields.items():
        lines.extend((
            '--{0}'.format(boundary),
            'Content-Disposition: form-data; name="{0}"'.format(escape_quote(name)),
            '',
            str(value),
        ))

    for name, value in files.items():
        filename = value['filename']
        if 'mimetype' in value:
            mimetype = value['mimetype']
        else:
            mimetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        lines.extend((
            '--{0}'.format(boundary),
            'Content-Disposition: form-data; name="{0}"; filename="{1}"'.format(
                    escape_quote(name), escape_quote(filename)),
            'Content-Type: {0}'.format(mimetype),
            '',
            value['content'],
        ))

    lines.extend((
        '--{0}--'.format(boundary),
        '',
    ))
    body = '\r\n'.join(lines)

    headers = {
        'Content-Type': 'multipart/form-data; boundary={0}'.format(boundary),
        'Content-Length': str(len(body)),
    }
    return (body, headers)


def upload_file(filepath, url, permission, signature, key=None, move_files=True):
        '''
        Upload file at filepath.

        Move to subfolders 'success'/'failed' on completion if move_files is True.
        '''
        filename = os.path.basename(filepath)
        print("Uploading: {0}".format(filename))

        # add S3 'path' if given
        if key is None:
            s3_key = filename
        else:
            s3_key = key+filename

        parameters = {"key": s3_key, "AWSAccessKeyId": "AKIAI2X3BJAT2W75HILA", "acl": "private",
                    "policy": permission, "signature": signature, "Content-Type":"image/jpeg" }

        with open(filepath, "rb") as f:
            encoded_string = f.read()

        data, headers = encode_multipart(parameters, {'file': {'filename': filename, 'content': encoded_string}})

        for attempt in range(MAX_ATTEMPTS):
            try:
                request = urllib2.Request(url, data=data, headers=headers)
                response = urllib2.urlopen(request)

                if response.getcode()==204:
                    if move_files:
                        os.rename(filepath, "success/"+filename)
                    print("Success: {0}".format(filename))
                else:
                    if move_files:
                        os.rename(filepath, "failed/"+filename)
                    print("Failed: {0}".format(filename))
                break # attempts

            except urllib2.HTTPError as e:
                print("HTTP error: {0} on {1}".format(e, filename))
                time.sleep(5)
            except urllib2.URLError as e:
                print("URL error: {0} on {1}".format(e, filename))
                time.sleep(5)
            except OSError as e:
                print("OS error: {0} on {1}".format(e, filename))
                time.sleep(5)
            except socket.timeout as e:
                # Specific timeout handling for Python 2.7
                print("Timeout error: {0} (retrying)".format(filename))


def create_dirs():
    if not os.path.exists("success"):
        os.mkdir("success")
    if not os.path.exists("failed"):
        os.mkdir("failed")


def exif_has_mapillary_tags(filename):
    '''
    Check that image file has the required Mapillary tags in EXIF fields.
    '''
    description_tag = "Image ImageDescription"
    with open(filename, 'rb') as f:
        tags = exifread.process_file(f)

    # make sure there are Mapillary tags in Image Decription
    if description_tag in tags:
        if "MAPSequenceUUID" in tags[description_tag].values:
            return True
        else:
            print("File does not have Mapillary EXIF tags, consider using upload_with_authentication.py instead.")
            return False
    else:
        print("File does not have any Image Description in EXIF tags.")
        return False


class UploadThread(threading.Thread):
    def __init__(self, queue, params=UPLOAD_PARAMS):
        threading.Thread.__init__(self)
        self.q = queue
        self.params = params

    def run(self):
        while True:
            # fetch file from the queue and upload
            filepath = self.q.get()
            if filepath is None:
                self.q.task_done()
                break
            else:
                upload_file(filepath, **self.params)
                self.q.task_done()



if __name__ == '__main__':
    '''
    Use from command line as: python upload.py path
    '''

    if sys.version_info >= (3, 0):
        raise IOError("Incompatible Python version. This script requires Python 2.x, you are using {0}.".format(sys.version_info[:2]))
    
    if len(sys.argv) > 2:
        print("Usage: python upload.py path")
        raise IOError("Bad input parameters.")

    path = sys.argv[1]

    # if no success/failed folders, create them
    create_dirs()

    if path.lower().endswith(".jpg"):
        # single file
        file_list = [path]
    else:
        # folder(s)
        file_list = []
        for root, sub_folders, files in os.walk(path):
            file_list += [os.path.join(root, filename) for filename in files if filename.lower().endswith(".jpg")]

    # create upload queue with all files
    q = Queue()
    for filepath in file_list:
        if exif_has_mapillary_tags(filepath):
            q.put(filepath)
        else:
            print("Skipping: {0}".format(filepath))

    # create uploader threads
    uploaders = [UploadThread(q) for i in range(NUMBER_THREADS)]

    # start uploaders as daemon threads that can be stopped (ctrl-c)
    try:
        for uploader in uploaders:
            uploader.daemon = True
            uploader.start()

        for uploader in uploaders:
            uploaders[i].join(1)

        while q.unfinished_tasks:
            time.sleep(1)
        q.join()
    except (KeyboardInterrupt, SystemExit):
        print("\nBREAK: Stopping upload.")
        sys.exit()

    print("Done uploading.")
