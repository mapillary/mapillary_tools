#!/usr/bin/python

import sys
import urllib2, urllib
import os
import base64
import mimetypes
import random
import string
from Queue import Queue
import threading

'''
Script for uploading images taken with the Mapillary
iOS or Android apps.

Intended use is for cases when you have multiple SD cards
or for other reasons have copied the files to a computer
and you want to bulk upload.

NB: DO NOT USE THIS ON OTHER IMAGE FILES THAN THOSE FROM
THE MAPILLARY APPS, WITHOUT PROPER TOKENS IN EXIF, UPLOADED
FILES WILL BE IGNORED SERVER-SIDE.
'''

MAPILLARY_UPLOAD_URL = "http://mapillary.uploads.images.s3.amazonaws.com/"
PERMISSION_HASH = "eyJleHBpcmF0aW9uIjoiMjAyMC0wMS0wMVQwMDowMDowMFoiLCJjb25kaXRpb25zIjpbeyJidWNrZXQiOiJtYXBpbGxhcnkudXBsb2Fkcy5pbWFnZXMifSxbInN0YXJ0cy13aXRoIiwiJGtleSIsIiJdLHsiYWNsIjoicHJpdmF0ZSJ9LFsic3RhcnRzLXdpdGgiLCIkQ29udGVudC1UeXBlIiwiIl0sWyJjb250ZW50LWxlbmd0aC1yYW5nZSIsMCwxMDQ4NTc2MF1dfQ=="
SIGNATURE_HASH = "foNqRicU/vySm8/qU82kGESiQhY="
BOUNDARY_CHARS = string.digits + string.ascii_letters
NUMBER_THREADS = 4


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


def upload_file(filepath, move_files=True):
    '''
    Upload file at filepath.

    Move to subfolders 'success'/'failed' on completion if move_files is True.
    '''
    filename = os.path.basename(filepath)
    print("Uploading: {0}".format(filename))

    parameters = {"key": filename, "AWSAccessKeyId": "AKIAI2X3BJAT2W75HILA", "acl": "private",
                "policy": PERMISSION_HASH, "signature": SIGNATURE_HASH, "Content-Type":"image/jpeg" }

    with open(filepath, "rb") as f:
        encoded_string = f.read()

    data, headers = encode_multipart(parameters, {'file': {'filename': filename, 'content': encoded_string}})
    request = urllib2.Request(MAPILLARY_UPLOAD_URL, data=data, headers=headers)
    response = urllib2.urlopen(request)

    if response.getcode()==204:
        if move_files==True:
            os.rename(filepath, "success/"+filename)
        else:
            os.remove(filepath)

        print("Success: {0}".format(filename))
    else:
        os.rename(filepath, "failed/"+filename)
        print("Failed: {0}".format(filename))


def create_dirs():
    if not os.path.exists("success"):
        os.mkdir("success")
    if not os.path.exists("failed"):
        os.mkdir("failed")


class UploadThread(threading.Thread):
    def __init__(self, queue, move_files):
        threading.Thread.__init__(self)
        self.q = queue
        self.move = move_files

    def run(self):
        while True:
            # fetch file from the queue and upload
            filepath = self.q.get()
            if filepath is None:
                self.q.task_done()
                break
            else:
                upload_file(filepath, self.move)
                self.q.task_done()



if __name__ == '__main__':
    '''
    Use from command line as: python upload.py path
    '''

    if len(sys.argv) > 3:
        print("Usage: python upload.py path")
        raise IOError("Bad input parameters.")

    path = sys.argv[1]

    move_files = True
    if ( len(sys.argv) == 3 and sys.argv[2] == '-d' ):
        move_files=False

    # if no success/failed folders, create them
    create_dirs()

    if path.endswith(".jpg"):
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
        q.put(filepath)

    # create uploader threads
    uploaders = [UploadThread(q, move_files) for i in range(NUMBER_THREADS)]

    # start uploaders as daemon threads that can be stopped (ctrl-c)
    try:
        for uploader in uploaders:
            uploader.daemon = True
            uploader.start()

        q.join()
        for uploader in uploaders:
            uploaders[i].join(1)
    except (KeyboardInterrupt, SystemExit):
        print("BREAK: Stopping upload.")
        sys.exit()

    print("Done uploading.")
