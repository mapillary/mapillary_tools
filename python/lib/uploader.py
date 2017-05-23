from lib.exif import EXIF
import lib.io
import json
import os
import string
import threading
import sys
import urllib2, urllib, httplib
import socket
import mimetypes
import random
import string
from Queue import Queue
import threading
import exifread
import time


MAPILLARY_UPLOAD_URL = "https://d22zcsn13kp53w.cloudfront.net/"
MAPILLARY_DIRECT_UPLOAD_URL = "https://s3-eu-west-1.amazonaws.com/mapillary.uploads.images"
PERMISSION_HASH = "eyJleHBpcmF0aW9uIjoiMjAyMC0wMS0wMVQwMDowMDowMFoiLCJjb25kaXRpb25zIjpbeyJidWNrZXQiOiJtYXBpbGxhcnkudXBsb2Fkcy5pbWFnZXMifSxbInN0YXJ0cy13aXRoIiwiJGtleSIsIiJdLHsiYWNsIjoicHJpdmF0ZSJ9LFsic3RhcnRzLXdpdGgiLCIkQ29udGVudC1UeXBlIiwiIl0sWyJjb250ZW50LWxlbmd0aC1yYW5nZSIsMCwyMDQ4NTc2MF1dfQ=="
SIGNATURE_HASH = "f6MHj3JdEq8xQ/CmxOOS7LvMxoI="
BOUNDARY_CHARS = string.digits + string.ascii_letters
NUMBER_THREADS = int(os.getenv('NUMBER_THREADS', '4'))
MAX_ATTEMPTS = int(os.getenv('MAX_ATTEMPTS', '10'))
UPLOAD_PARAMS = {"url": MAPILLARY_UPLOAD_URL, "permission": PERMISSION_HASH, "signature": SIGNATURE_HASH, "move_files":True,  "keep_file_names": True}

class UploadThread(threading.Thread):
    def __init__(self, queue, params=UPLOAD_PARAMS):
        threading.Thread.__init__(self)
        self.q = queue
        self.params = params
        self.total_task = self.q.qsize()

    def run(self):
        while True:
            # fetch file from the queue and upload
            filepath = self.q.get()
            if filepath is None:
                self.q.task_done()
                break
            else:
                lib.io.progress(self.total_task-self.q.qsize(), self.total_task, '... {} images left.'.format(self.q.qsize()))
                upload_file(filepath, **self.params)
                self.q.task_done()


def create_dirs(root_path=''):
    lib.io.mkdir_p(os.path.join(root_path, "success"))
    lib.io.mkdir_p(os.path.join(root_path, "failed"))


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


def finalize_upload(params, retry=3, auto_done=False):
    '''
    Finalize and confirm upload
    '''
    # retry if input is unclear
    for i in range(retry):
        if not auto_done:
            proceed = raw_input("Finalize upload? [y/n]: ")
        else:
            proceed = "y"
        if proceed in ["y", "Y", "yes", "Yes"]:
            # upload an empty DONE file
            upload_done_file(params)
            print("Done uploading.")
            break
        elif proceed in ["n", "N", "no", "No"]:
            print("Aborted. No files were submitted. Try again if you had failures.")
            break
        else:
            if i==2:
                print("Aborted. No files were submitted. Try again if you had failures.")
            else:
                print('Please answer y or n. Try again.')

def get_upload_token(mail, pwd):
    '''
    Get upload token
    '''
    params = urllib.urlencode({"email": mail, "password": pwd})
    response = urllib.urlopen("https://a.mapillary.com/v1/u/login", params)
    resp = json.loads(response.read())
    return resp['upload_token']


def get_authentication_info():
    '''
    Get authentication information from env
    '''
    try:
        MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
        MAPILLARY_EMAIL = os.environ['MAPILLARY_EMAIL']
        MAPILLARY_PASSWORD = os.environ['MAPILLARY_PASSWORD']
    except KeyError:
        return None
    return MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD


def get_full_authentication_info(user=None, email=None):
    # Fetch full authetication info
    try:
        MAPILLARY_EMAIL = email if email is not None else os.environ['MAPILLARY_EMAIL']
        MAPILLARY_SECRET_HASH = os.environ.get('MAPILLARY_SECRET_HASH', None)
        MAPILLARY_UPLOAD_TOKEN = None

        if MAPILLARY_SECRET_HASH is None:
            MAPILLARY_PASSWORD = os.environ['MAPILLARY_PASSWORD']
            MAPILLARY_PERMISSION_HASH = os.environ['MAPILLARY_PERMISSION_HASH']
            MAPILLARY_SIGNATURE_HASH = os.environ['MAPILLARY_SIGNATURE_HASH']
            MAPILLARY_UPLOAD_TOKEN = get_upload_token(MAPILLARY_EMAIL, MAPILLARY_PASSWORD)
            UPLOAD_URL = MAPILLARY_UPLOAD_URL
        else:
            secret_hash = MAPILLARY_SECRET_HASH
            MAPILLARY_PERMISSION_HASH = PERMISSION_HASH
            MAPILLARY_SIGNATURE_HASH = SIGNATURE_HASH
            UPLOAD_URL = MAPILLARY_DIRECT_UPLOAD_URL
        return MAPILLARY_EMAIL, MAPILLARY_UPLOAD_TOKEN, MAPILLARY_SECRET_HASH, UPLOAD_URL
    except KeyError:
        print("You are missing one of the environment variables MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD, MAPILLARY_PERMISSION_HASH or MAPILLARY_SIGNATURE_HASH. These are required.")
        sys.exit()


def get_project_key(project_name):
    '''
    Get project key given project name
    '''
    if project_name is not None:
        MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD = get_authentication_info()
        params = urllib.urlencode( {"email": MAPILLARY_EMAIL, "password": MAPILLARY_PASSWORD })
        response = urllib.urlopen("https://a.mapillary.com/v1/u/login", params)
        response_read = response.read()
        resp = json.loads(response_read)
        projects = resp['projects']

        # check projects
        found = False
        print "Your projects: "
        for project in projects:
            print project["name"]
            if project['name'].decode('utf-8') == project_name:
                found = True
                project_key = project['key']
                return project_key

        if not found:
            print "Project {} not found.".format(project_name)

    return ""


def upload_done_file(params):
    print("Upload a DONE file {} to indicate the sequence is all uploaded and ready to submit.".format(params['key']))
    if not os.path.exists("DONE"):
        open("DONE", 'a').close()
    #upload
    upload_file("DONE", **params)
    #remove
    if os.path.exists("DONE"):
        os.remove("DONE")


def upload_file(filepath, url, permission, signature, key=None, move_files=True, keep_file_names=True):
    '''
    Upload file at filepath.

    Move to subfolders 'success'/'failed' on completion if move_files is True.
    '''
    filename = os.path.basename(filepath)

    if keep_file_names:
        s3_filename = filename
    else:
        try:
            s3_filename = EXIF(filepath).exif_name()
        except:
            s3_filename = filename

    # add S3 'path' if given
    if key is None:
        s3_key = s3_filename
    else:
        s3_key = key+s3_filename

    parameters = {"key": s3_key, "AWSAccessKeyId": "AKIAI2X3BJAT2W75HILA", "acl": "private",
                "policy": permission, "signature": signature, "Content-Type":"image/jpeg" }

    with open(filepath, "rb") as f:
        encoded_string = f.read()

    data, headers = encode_multipart(parameters, {'file': {'filename': filename, 'content': encoded_string}})

    root_path = os.path.dirname(filepath)
    success_path = os.path.join(root_path, 'success')
    failed_path = os.path.join(root_path, 'failed')
    lib.io.mkdir_p(success_path)
    lib.io.mkdir_p(failed_path)

    for attempt in range(MAX_ATTEMPTS):
        try:
            request = urllib2.Request(url, data=data, headers=headers)
            response = urllib2.urlopen(request)

            if response.getcode()==204:
                if move_files:
                    os.rename(filepath, os.path.join(success_path, filename))
                # print("Success: {0}".format(filename))
            else:
                if move_files:
                    os.rename(filepath, os.path.join(failed_path,filename))
                print("Failed: {0}".format(filename))
            break # attempts

        except urllib2.HTTPError as e:
            print("HTTP error: {0} on {1}".format(e, filename))
            time.sleep(5)
        except urllib2.URLError as e:
            print("URL error: {0} on {1}".format(e, filename))
            time.sleep(5)
        except httplib.HTTPException as e:
            print("HTTP exception: {0} on {1}".format(e, filename))
            time.sleep(5)
        except OSError as e:
            print("OS error: {0} on {1}".format(e, filename))
            time.sleep(5)
        except socket.timeout as e:
            # Specific timeout handling for Python 2.7
            print("Timeout error: {0} (retrying)".format(filename))
        finally:
            if response is not None:
                response.close()


def upload_file_list(file_list, params=UPLOAD_PARAMS):
    # create upload queue with all files
    q = Queue()
    for filepath in file_list:
        q.put(filepath)

    # create uploader threads
    uploaders = [UploadThread(q, params) for i in range(NUMBER_THREADS)]

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


def upload_summary(file_list, total_uploads, split_groups, duplicate_groups, missing_groups):
    total_success = len([f for f in file_list if 'success' in f])
    total_failed = len([f for f in file_list if 'failed' in f])
    lines = []
    if duplicate_groups:
        lines.append('Duplicates (skipping):')
        lines.append('  groups:       {}'.format(len(duplicate_groups)))
        lines.append('  total:        {}'.format(sum([len(g) for g in duplicate_groups])))
    if missing_groups:
        lines.append('Missing Required EXIF (skipping):')
        lines.append('  total:        {}'.format(sum([len(g) for g in missing_groups])))

    lines.append('Sequences:')
    lines.append('  groups:       {}'.format(len(split_groups)))
    lines.append('  total:        {}'.format(sum([len(g) for g in split_groups])))
    lines.append('Uploads:')
    lines.append('  total uploads this run: {}'.format(total_uploads))
    lines.append('  total:        {}'.format(total_success+total_failed))
    lines.append('  success:      {}'.format(total_success))
    lines.append('  failed:       {}'.format(total_failed))
    lines = '\n'.join(lines)
    return lines
