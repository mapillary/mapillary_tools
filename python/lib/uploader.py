from lib.exif_read import ExifRead
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
import time
import config


MAPILLARY_UPLOAD_URL = "https://d22zcsn13kp53w.cloudfront.net/"
MAPILLARY_DIRECT_UPLOAD_URL = "https://s3-eu-west-1.amazonaws.com/mapillary.uploads.images"
PERMISSION_HASH = "eyJleHBpcmF0aW9uIjoiMjAyMC0wMS0wMVQwMDowMDowMFoiLCJjb25kaXRpb25zIjpbeyJidWNrZXQiOiJtYXBpbGxhcnkudXBsb2Fkcy5pbWFnZXMifSxbInN0YXJ0cy13aXRoIiwiJGtleSIsIiJdLHsiYWNsIjoicHJpdmF0ZSJ9LFsic3RhcnRzLXdpdGgiLCIkQ29udGVudC1UeXBlIiwiIl0sWyJjb250ZW50LWxlbmd0aC1yYW5nZSIsMCwyMDQ4NTc2MF1dfQ=="
SIGNATURE_HASH = "f6MHj3JdEq8xQ/CmxOOS7LvMxoI="
BOUNDARY_CHARS = string.digits + string.ascii_letters
NUMBER_THREADS = int(os.getenv('NUMBER_THREADS', '4'))
MAX_ATTEMPTS = int(os.getenv('MAX_ATTEMPTS', '10'))
UPLOAD_PARAMS = {"url": MAPILLARY_UPLOAD_URL, "permission": PERMISSION_HASH, "signature": SIGNATURE_HASH} # TODO move_files should not exist anymore
CLIENT_ID = "MkJKbDA0bnZuZlcxeTJHTmFqN3g1dzo1YTM0NjRkM2EyZGU5MzBh"
LOGIN_URL = "https://a.mapillary.com/v2/ua/login?client_id={}".format(CLIENT_ID)
PROJECTS_URL = "https://a.mapillary.com/v3/users/{}/projects?client_id={}"
ME_URL = "https://a.mapillary.com/v3/me?client_id={}".format(CLIENT_ID)
UPLOAD_STATUS_PAIRS={"upload_success":"upload_failed",
                     "upload_failed":"upload_success"}
LOCAL_CONFIG_FILEPATH = os.path.join(
    os.path.expanduser('~'), '{}.mapillary/config')
GLOBAL_CONFIG_FILEPATH = os.path.expanduser('~/.config/mapillary/config')

class UploadThread(threading.Thread):
    def __init__(self, queue, root): # TODO params are joint in the queue
        threading.Thread.__init__(self)
        self.q = queue
        self.root = root
        self.total_task = self.q.qsize()

    def run(self):
        while True:
            # fetch file from the queue and upload
            filepath, params = self.q.get() # TODO return filepath and params per filepath ....filepath, params
            if filepath is None:
                self.q.task_done()
                break
            else:
                lib.io.progress(self.total_task-self.q.qsize(), self.total_task, '... {} images left.'.format(self.q.qsize()))
                upload_file(filepath, self.root, **params)
                self.q.task_done()

def encode_multipart(fields, files, boundary=None): #TODO note that this is not looked into, but left as out of improvement scope
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


def finalize_upload(params, retry=3, auto_done=False): #TODO check where this is called with auto_done=True and where it is left with defualt auto_done=False and why
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
            upload_done_file(params) #TODO check if this is in all uploads or only for the manual.upload ones
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
    #TODO this is to get the upload hash, it is called here in the  get_full_authentication_info(user, email), a function which is called only in the obsolete? export_panoramio.py, with the user email only
    #and in upload_with_preprocessing.py in the middle of everything, where email and username and userkey are read from os environment or args and password is also stored in os environment(f real)
    '''
    Get upload token
    '''
    params = urllib.urlencode({"email": mail, "password": pwd})
    response = urllib.urlopen(LOGIN_URL, params)
    resp = json.loads(response.read())
    return resp['token']


def prompt_user_for_user_items():
    user_items = None
    user_items["user_email"] = raw_input("Enter email : ")
    user_items["user_password"] = raw_input("Enter password : ")
    user_items["user_key"] = raw_input("Enter user key : ")
    user_items["user_permission_hash"] = raw_input(
        "Enter user permission hash : ")
    user_items["user_signature_hash"] = raw_input(
        "Enter user signature hash : ")
    user_items["upload_token"] = get_upload_token(
        user_items["user_email"], user_items["user_password"])
    return user_items


def authenticate_user(user_name, import_path):
    local_config_filepath = LOCAL_CONFIG_FILEPATH.format(import_path)
    user_items = None
    if os.path.isfile(local_config_filepath):
        local_config_object = config.load_config(local_config_filepath)
        if user_name in local_config_object.sections:
            user_items = config.load_user(local_config_object, user_name)
            return user_items
    elif os.path.isfile(GLOBAL_CONFIG_FILEPATH):
        global_config_object = config.load_config(GLOBAL_CONFIG_FILEPATH)
        if user_name in global_config_object.sections:
            user_items = config.load_user(global_config_object, user_name)
            config.create_config(local_config_filepath)
            config.initialize_config(
                local_config_filepath, user_name, user_items)
            return user_items
        else:
            print("enter user credentials for user " + user_name)
            user_items = prompt_user_for_user_items()
            config.initialize_config(
                GLOBAL_CONFIG_FILEPATH, user_name, user_items)
            config.create_config(local_config_filepath)
            config.initialize_config(
                local_config_filepath, user_name, user_items)
            return user_items
    else:
        print("enter user credentials for user " + user_name)
        user_items = prompt_user_for_user_items()
        config.create_config(GLOBAL_CONFIG_FILEPATH)
        config.initialize_config(
            GLOBAL_CONFIG_FILEPATH, user_name, user_items)
        config.create_config(local_config_filepath)
        config.initialize_config(
            local_config_filepath, user_name, user_items)
        return user_items

def get_authentication_info(username):
    '''
    Get authentication information from config
    '''
    
    #TODO check if global config exists, if not create it for the username and prompt for the required info
    #TODO if config exists, check for the username, if username not in the config, prompt for required info
    #TODO set local config file
    try:
        MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
        MAPILLARY_EMAIL = os.environ['MAPILLARY_EMAIL']
        MAPILLARY_PASSWORD = os.environ['MAPILLARY_PASSWORD']
    except KeyError:
        return None
    return MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD

def get_project_key(project_name, project_key=None): #TODO, consider if this will be changed(does this even work now?), this is called in upload_with_preprocessing and add_mapillary_tag_from_json, just to validate project, and in add_project, to obtain the key and write it in the image description
    '''
    Get project key given project name
    '''
    if project_name is not None or project_key is not None:

        # Get the JWT token
        MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD = get_authentication_info()
        params = urllib.urlencode( {"email": MAPILLARY_EMAIL, "password": MAPILLARY_PASSWORD })
        resp = json.loads(urllib.urlopen(LOGIN_URL, params).read())
        token = resp['token']

        # Get the user key
        req = urllib2.Request(ME_URL)
        req.add_header('Authorization', 'Bearer {}'.format(token))
        resp = json.loads(urllib2.urlopen(req).read())
        userkey = resp['key']

        # Get the user key
        req = urllib2.Request(PROJECTS_URL.format(userkey, CLIENT_ID))
        req.add_header('Authorization', 'Bearer {}'.format(token))
        resp = json.loads(urllib2.urlopen(req).read())
        projects = resp

        # check projects
        found = False
        print "Your projects: "
        for project in projects:
            print(project["name"])
            project_name_matched = project['name'].encode('utf-8').decode('utf-8') == project_name
            project_key_matched = project["key"] == project_key
            if project_name_matched or project_key_matched:
                found = True
                return project['key']

        if not found:
            print "Project {} not found.".format(project_name)

    return ""


def upload_done_file(params):#TODO note that this will stay the same
    print("Upload a DONE file {} to indicate the sequence is all uploaded and ready to submit.".format(params['key']))
    if not os.path.exists("DONE"):
        open("DONE", 'a').close()
    #upload
    upload_file("DONE",None, **params)
    #remove
    if os.path.exists("DONE"):
        os.remove("DONE")

def upload_file(filepath, root, url, permission, signature, key=None):#TODO , this needs changing, move_files should not exist anymore
    '''
    Upload file at filepath.

    '''    
    filename = os.path.basename(filepath)

    s3_filename = filename
    if root!=None:
        try:
            s3_filename = ExifRead(filepath).exif_name()
        except:
            pass

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

    for attempt in range(MAX_ATTEMPTS):
    
        # Initialize response before each attempt
        response = None
    
        try:
            #request = urllib2.Request(url, data=data, headers=headers)
            #response = urllib2.urlopen(request)
            #if response.getcode()==204:
            if 1:
                create_upload_log(root, filepath, "upload_success")
            else:
                create_upload_log(root, filepath, "upload_failed")
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


def upload_file_list(file_list, root, file_params={}):
    # create upload queue with all files
    q = Queue()
    for filepath in file_list:
        if filepath not in file_params:
            q.put((filepath, UPLOAD_PARAMS))
        else:
            q.put((filepath, file_params[filepath]))
    # create uploader threads
    uploaders = [UploadThread(q, root) for i in range(NUMBER_THREADS)]

    # start uploaders as daemon threads that can be stopped (ctrl-c)
    try:
        print("Uploading with {} threads".format(NUMBER_THREADS))
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

def upload_log_rootpath(root,filepath):
    return os.path.join(root,".mapillary/logs",filepath.split(root)[1][1:-4])

def create_upload_log(root, filepath, status):
    upload_log_root=upload_log_rootpath(root,filepath)
    upload_log_filepath=os.path.join(upload_log_root,status)
    upload_opposite_log_filepath=os.path.join(upload_log_root,UPLOAD_STATUS_PAIRS[status])
    if not os.path.isdir(upload_log_root):
        os.makedirs(upload_log_root)
        open(upload_log_filepath, "w").close()
        open(upload_log_filepath+"_"+str(time.strftime("%Y:%m:%d %H:%M:%S", time.gmtime())),"w").close()
    else:
        if not os.path.isfile(upload_log_filepath):
            open(upload_log_filepath, "w").close()
            open(upload_log_filepath+"_"+str(time.strftime("%Y:%m:%d %H:%M:%S", time.gmtime())),"w").close()
        if os.path.isfile(upload_opposite_log_filepath):
            os.remove(upload_opposite_log_filepath)

def upload_summary(file_list, total_uploads, split_groups, duplicate_groups, missing_groups): #TODO change this, to summarize the upload.log and the processing.log maybe, now only used in upload_wth_preprocessing
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
