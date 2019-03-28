from exif_read import ExifRead
import json
import os
import urllib2
import urllib
import httplib
import datetime
import socket
import mimetypes
import random
import string
from Queue import Queue
import threading
import time
import config
import getpass
import sys
import processing
import requests
import yaml
from tqdm import tqdm
from . import ipc
from .error import print_error
from .utils import force_decode
from gpx_from_blackvue import gpx_from_blackvue, get_points_from_bv
from process_video import get_video_duration
from process_video import get_video_start_time_blackvue
from geo import get_timezone_and_utc_offset
from camera_support.prepare_blackvue_videos import get_blackvue_info
if os.getenv("AWS_S3_ENDPOINT", None) is None:
    MAPILLARY_UPLOAD_URL = "https://secure-upload.mapillary.com"
else:
    MAPILLARY_UPLOAD_URL = "{}/{}".format(
        os.getenv("AWS_S3_ENDPOINT"), "mtf-upload-images")

MAPILLARY_DIRECT_UPLOAD_URL = "https://s3-eu-west-1.amazonaws.com/mapillary.uploads.images"
PERMISSION_HASH = "eyJleHBpcmF0aW9uIjoiMjAyMC0wMS0wMVQwMDowMDowMFoiLCJjb25kaXRpb25zIjpbeyJidWNrZXQiOiJtYXBpbGxhcnkudXBsb2Fkcy5pbWFnZXMifSxbInN0YXJ0cy13aXRoIiwiJGtleSIsIiJdLHsiYWNsIjoicHJpdmF0ZSJ9LFsic3RhcnRzLXdpdGgiLCIkQ29udGVudC1UeXBlIiwiIl0sWyJjb250ZW50LWxlbmd0aC1yYW5nZSIsMCwyMDQ4NTc2MF1dfQ=="
SIGNATURE_HASH = "f6MHj3JdEq8xQ/CmxOOS7LvMxoI="
BOUNDARY_CHARS = string.digits + string.ascii_letters
NUMBER_THREADS = int(os.getenv('NUMBER_THREADS', '5'))
MAX_ATTEMPTS = int(os.getenv('MAX_ATTEMPTS', '50'))
UPLOAD_PARAMS = {"url": MAPILLARY_UPLOAD_URL, "permission": PERMISSION_HASH,  # TODO: This URL is dynamic in api 2.0
                 "signature": SIGNATURE_HASH, "aws_key": "AKIAI2X3BJAT2W75HILA"}
CLIENT_ID = os.getenv("MAPILLARY_WEB_CLIENT_ID",
                      "MkJKbDA0bnZuZlcxeTJHTmFqN3g1dzo1YTM0NjRkM2EyZGU5MzBh")
DRY_RUN = bool(os.getenv('DRY_RUN', False))

if os.getenv("API_PROXY_HOST", None) is None:
    API_ENDPOINT = "https://a.mapillary.com"
else:
    API_ENDPOINT = "http://{}".format(os.getenv("API_PROXY_HOST"))
LOGIN_URL = "{}/v2/ua/login?client_id={}".format(API_ENDPOINT, CLIENT_ID)
ORGANIZATIONS_URL = API_ENDPOINT + "/v3/users/{}/organizations?client_id={}"
USER_URL = API_ENDPOINT + "/v3/users?usernames={}&client_id={}"
ME_URL = "{}/v3/me?client_id={}".format(API_ENDPOINT, CLIENT_ID)
USER_UPLOAD_URL = API_ENDPOINT + "/v3/users/{}/upload_tokens?client_id={}"
UPLOAD_STATUS_PAIRS = {"upload_success": "upload_failed",
                       "upload_failed": "upload_success"}
GLOBAL_CONFIG_FILEPATH = os.getenv("GLOBAL_CONFIG_FILEPATH", os.path.join(os.path.expanduser('~'),
                                                                          ".config", "mapillary", 'config'))


class UploadThread(threading.Thread):
    def __init__(self, queue):
        threading.Thread.__init__(self)
        self.q = queue
        self.total_task = self.q.qsize()

    def run(self):
        while True:
            # fetch file from the queue and upload
            filepath, max_attempts, params = self.q.get()
            if filepath is None:
                self.q.task_done()
                break
            else:
                progress(self.total_task - self.q.qsize(), self.total_task,
                         '... {} images left.'.format(self.q.qsize()))
                upload_file(filepath, max_attempts, **params)
                self.q.task_done()


# TODO note that this is not looked into, but left as out of improvement scope
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
            'Content-Disposition: form-data; name="{0}"'.format(
                escape_quote(name)),
            '',
            str(value),
        ))

    for name, value in files.items():
        filename = value['filename']
        if 'mimetype' in value:
            mimetype = value['mimetype']
        else:
            mimetype = mimetypes.guess_type(
                filename)[0] or 'application/octet-stream'
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


def prompt_to_finalize(subcommand):
    for i in range(3):
        finalize = raw_input(
            "Finalize all {} in this import? [y/n]: ".format(subcommand))
        if finalize in ["y", "Y", "yes", "Yes"]:
            return 1
        elif finalize in ["n", "N", "no", "No"]:
            return 0
        else:
            print('Please answer y or n. Try again.')
    return 0


def flag_finalization(finalize_file_list):
    for file in finalize_file_list:
        finalize_flag = os.path.join(log_rootpath(file), "upload_finalized")
        open(finalize_flag, 'a').close()


def get_upload_url(credentials):
    '''
    Returns upload URL using new upload API
    '''
    request_url = "https://a.mapillary.com/v3/users/{}/upload_secrets?client_id={}".format(
        credentials["MAPSettingsUserKey"], CLIENT_ID)
    request = urllib2.Request(request_url)
    request.add_header('Authorization', 'Bearer {}'.format(
        credentials["user_upload_token"]))
    try:
        response = json.loads(urllib2.urlopen(request).read())
    except requests.exceptions.HTTPError as e:
        print("Error getting upload parameters, upload could not start")
        sys.exit(1)
    return response


def get_upload_file_list(import_path, skip_subfolders=False):
    upload_file_list = []
    if skip_subfolders:
        upload_file_list.extend(os.path.join(os.path.abspath(import_path), file) for file in os.listdir(import_path) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and preform_upload(import_path, file))
    else:
        for root, dir, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            upload_file_list.extend(os.path.join(os.path.abspath(root), file) for file in files if file.lower().endswith(
                ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and preform_upload(root, file))
    return sorted(upload_file_list)


# get a list of video files in a video_file
# TODO: Create list of supported files instead of adding only these 3
def get_video_file_list(video_file, skip_subfolders=False):
    video_file_list = []
    if skip_subfolders:
        video_file_list.extend(os.path.join(os.path.abspath(video_file), file)
                               for file in os.listdir(video_file) if (file.lower().endswith(('mp4')) or file.lower().endswith(('tavi')) or file.lower().endswith(('avi')) or file.lower().endswith(('mov'))))
    else:
        for root, dir, files in os.walk(video_file):
            video_file_list.extend(os.path.join(os.path.abspath(root), file)
                                   for file in files if (file.lower().endswith(('mp4')) or file.lower().endswith(('tavi')) or file.lower().endswith(('avi')) or file.lower().endswith(('mov'))))
    return sorted(video_file_list)


def get_total_file_list(import_path, skip_subfolders=False):
    total_file_list = []
    if skip_subfolders:
        total_file_list.extend(os.path.join(os.path.abspath(import_path), file) for file in os.listdir(import_path) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')))
    else:
        for root, dir, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            total_file_list.extend(os.path.join(os.path.abspath(root), file) for file in files if file.lower(
            ).endswith(('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')))
    return sorted(total_file_list)


def get_failed_upload_file_list(import_path, skip_subfolders=False):
    failed_upload_file_list = []
    if skip_subfolders:
        failed_upload_file_list.extend(os.path.join(os.path.abspath(import_path), file) for file in os.listdir(import_path) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and failed_upload(import_path, file))
    else:
        for root, dir, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            failed_upload_file_list.extend(os.path.join(os.path.abspath(root), file) for file in files if file.lower(
            ).endswith(('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and failed_upload(root, file))

    return sorted(failed_upload_file_list)


def get_success_upload_file_list(import_path, skip_subfolders=False):
    success_upload_file_list = []
    if skip_subfolders:
        success_upload_file_list.extend(os.path.join(os.path.abspath(import_path), file) for file in os.listdir(import_path) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and success_upload(import_path, file))
    else:
        for root, dir, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            success_upload_file_list.extend(os.path.join(os.path.abspath(root), file) for file in files if file.lower(
            ).endswith(('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and success_upload(root, file))

    return sorted(success_upload_file_list)


def success_upload(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    upload_success = os.path.join(log_root, "upload_success")
    upload_finalization = os.path.join(log_root, "upload_finalized")
    manual_upload = os.path.join(log_root, "manual_upload")
    success = (os.path.isfile(
        upload_success) and not os.path.isfile(manual_upload)) or (os.path.isfile(upload_success) and os.path.isfile(manual_upload) and os.path.isfile(upload_finalization))
    return success


def get_success_only_manual_upload_file_list(import_path, skip_subfolders=False):
    success_only_manual_upload_file_list = []
    if skip_subfolders:
        success_only_manual_upload_file_list.extend(os.path.join(os.path.abspath(import_path), file) for file in os.listdir(import_path) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and success_only_manual_upload(import_path, file))
    else:
        for root, dir, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            success_only_manual_upload_file_list.extend(os.path.join(os.path.abspath(root), file) for file in files if file.lower(
            ).endswith(('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and success_only_manual_upload(root, file))

    return sorted(success_only_manual_upload_file_list)


def success_only_manual_upload(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    upload_success = os.path.join(log_root, "upload_success")
    manual_upload = os.path.join(log_root, "manual_upload")
    success = os.path.isfile(upload_success) and os.path.isfile(manual_upload)
    return success


def preform_upload(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    process_success = os.path.join(
        log_root, "mapillary_image_description_success")
    duplicate = os.path.join(log_root, "duplicate")
    upload_succes = os.path.join(log_root, "upload_success")
    upload = not os.path.isfile(upload_succes) and os.path.isfile(
        process_success) and not os.path.isfile(duplicate)
    return upload


def failed_upload(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    process_failed = os.path.join(
        log_root, "mapillary_image_description_failed")
    duplicate = os.path.join(log_root, "duplicate")
    upload_failed = os.path.join(log_root, "upload_failed")
    failed = os.path.isfile(
        upload_failed) and not os.path.isfile(process_failed) and not os.path.isfile(
        duplicate)
    return failed


def get_finalize_file_list(import_path, skip_subfolders=False):
    finalize_file_list = []
    if skip_subfolders:
        finalize_file_list.extend(os.path.join(os.path.abspath(import_path), file) for file in os.listdir(import_path) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and preform_finalize(import_path, file))
    else:
        for root, dir, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            finalize_file_list.extend(os.path.join(os.path.abspath(root), file) for file in files if file.lower().endswith(
                ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and preform_finalize(root, file))

    return sorted(finalize_file_list)


def preform_finalize(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    upload_succes = os.path.join(log_root, "upload_success")
    upload_finalized = os.path.join(log_root, "upload_finalized")
    manual_upload = os.path.join(log_root, "manual_upload")
    finalize = os.path.isfile(
        upload_succes) and not os.path.isfile(upload_finalized) and os.path.isfile(manual_upload)
    return finalize


def print_summary(file_list):
    # inform upload has finished and print out the summary
    print("Done uploading {} images.".format(
        len(file_list)))  # improve upload summary


def get_upload_token(mail, pwd):
    '''
    Get upload token
    '''
    try:
        params = urllib.urlencode({"email": mail, "password": pwd})
        response = urllib.urlopen(LOGIN_URL, params)
    except:
        return None
    resp = json.loads(response.read())
    if not resp or 'token' not in resp:
        return None
    return resp['token']


def get_organization_key(user_key, organization_username, upload_token):

    organization_key = None
    call = ORGANIZATIONS_URL.format(user_key, CLIENT_ID)
    req = urllib2.Request(call)
    req.add_header('Authorization', 'Bearer {}'.format(upload_token))
    resp = json.loads(urllib2.urlopen(req).read())

    organization_usernames = []
    for org in resp:
        organization_usernames.append(org['name'])
        if org['name'] == organization_username:
            organization_key = org['key']

    if not organization_key:
        print("No valid organization key found for organization user name " +
              organization_username)
        print("Available organization user names for current user are : ")
        print(organization_usernames)
        sys.exit(1)
    return organization_key


def validate_organization_key(user_key, organization_key, upload_token):

    call = ORGANIZATIONS_URL.format(user_key, CLIENT_ID)
    req = urllib2.Request(call)
    req.add_header('Authorization', 'Bearer {}'.format(upload_token))
    resp = json.loads(urllib2.urlopen(req).read())
    for org in resp:
        if org['key'] == organization_key:
            return
    print("Organization key does not exist.")
    sys.exit(1)


def validate_organization_privacy(user_key, organization_key, private, upload_token):

    call = ORGANIZATIONS_URL.format(user_key, CLIENT_ID)
    req = urllib2.Request(call)
    req.add_header('Authorization', 'Bearer {}'.format(upload_token))
    resp = json.loads(urllib2.urlopen(req).read())

    for org in resp:
        if org['key'] == organization_key:
            if (private and (('private_repository' not in org) or not org['private_repository'])) or (not private and (('public_repository' not in org) or not org['public_repository'])):
                print(
                    "Organization privacy does not match provided privacy settings.")
                privacy = "private" if 'private_repository' in org and org[
                    'private_repository'] else "public"
                privacy_provided = "private" if private else "public"
                print("Organization " +
                      org['name'] + " with key " + org['key'] + " is " + privacy + " while your import privacy settings state " + privacy_provided)
                sys.exit(1)


def progress(count, total, suffix=''):
    '''
    Display progress bar
    sources: https://gist.github.com/vladignatyev/06860ec2040cb497f0f3
    '''
    bar_len = 60
    filled_len = int(round(bar_len * count / float(total)))
    percents = round(100.0 * count / float(total), 1)
    bar = '=' * filled_len + '-' * (bar_len - filled_len)
    sys.stdout.write('[%s] %s%s %s\r' % (bar, percents, '%', suffix))
    sys.stdout.flush()


def prompt_user_for_user_items(user_name):
    user_items = {}
    print("Enter user credentials for user " + user_name + " :")
    user_email = raw_input("Enter email : ")
    user_password = getpass.getpass("Enter user password : ")
    user_key = get_user_key(user_name)
    if not user_key:
        return None
    upload_token = get_upload_token(
        user_email, user_password)
    if not upload_token:
        return None
    user_permission_hash, user_signature_hash = get_user_hashes(
        user_key, upload_token)

    user_items["MAPSettingsUsername"] = user_name
    user_items["MAPSettingsUserKey"] = user_key

    user_items["user_upload_token"] = upload_token
    user_items["user_permission_hash"] = user_permission_hash
    user_items["user_signature_hash"] = user_signature_hash

    return user_items

def authenticate_user(user_name):
    user_items = None
    if os.path.isfile(GLOBAL_CONFIG_FILEPATH):
        global_config_object = config.load_config(GLOBAL_CONFIG_FILEPATH)
        if user_name in global_config_object.sections():
            user_items = config.load_user(global_config_object, user_name)
            return user_items
    user_items = prompt_user_for_user_items(user_name)
    if not user_items:
        return None
    try:
        config.create_config(GLOBAL_CONFIG_FILEPATH)
    except Exception as e:
        print("Failed to create authentication config file due to {}".format(e))
        sys.exit(1)
    config.update_config(
        GLOBAL_CONFIG_FILEPATH, user_name, user_items)
    return user_items

def authenticate_with_email_and_pwd(user_email,user_password):
    '''
    Authenticate the user by passing the email and password.
    This function avoids prompting the command line for user credentials and is useful for calling tools programmatically
    '''
    if user_email is None or user_password is None:
        raise ValueError('Could not authenticate user. Missing username or password')
    upload_token = uploader.get_upload_token(user_email, user_password)
    if not upload_token:
        print("Authentication failed for user name " +
                user_name + ", please try again.")
        sys.exit(1)
    user_key = get_user_key(user_name)
    if not user_key:
        print("User name {} does not exist, please try again or contact Mapillary user support.".format(
            user_name))
        sys.exit(1)
    user_permission_hash, user_signature_hash = get_user_hashes(
        user_key, upload_token)

    user_items["MAPSettingsUsername"] = section
    user_items["MAPSettingsUserKey"] = user_key

    user_items["user_upload_token"] = upload_token
    user_items["user_permission_hash"] = user_permission_hash
    user_items["user_signature_hash"] = user_signature_hash
    return user_items

def get_master_key():
    master_key = ""
    if os.path.isfile(GLOBAL_CONFIG_FILEPATH):
        global_config_object = config.load_config(GLOBAL_CONFIG_FILEPATH)
        if "MAPAdmin" in global_config_object.sections():
            admin_items = config.load_user(global_config_object, "MAPAdmin")
            if "MAPILLARY_SECRET_HASH" in admin_items:
                master_key = admin_items["MAPILLARY_SECRET_HASH"]
            else:
                create_config = raw_input(
                    "Master upload key does not exist in your global Mapillary config file, set it now?")
                if create_config in ["y", "Y", "yes", "Yes"]:
                    master_key = set_master_key()
        else:
            create_config = raw_input(
                "MAPAdmin section not in your global Mapillary config file, set it now?")
            if create_config in ["y", "Y", "yes", "Yes"]:
                master_key = set_master_key()
    else:
        create_config = raw_input(
            "Master upload key needs to be saved in the global Mapillary config file, which does not exist, create one now?")
        if create_config in ["y", "Y", "yes", "Yes"]:
            config.create_config(GLOBAL_CONFIG_FILEPATH)
            master_key = set_master_key()

    return master_key


def set_master_key():
    config_object = config.load_config(GLOBAL_CONFIG_FILEPATH)
    section = "MAPAdmin"
    if section not in config_object.sections():
        config_object.add_section(section)
    master_key = raw_input("Enter the master key : ")
    if master_key != "":
        config_object = config.set_user_items(
            config_object, section, {"MAPILLARY_SECRET_HASH": master_key})
        config.save_config(config_object, GLOBAL_CONFIG_FILEPATH)
    return master_key


def get_user_key(user_name):
    try:
        req = urllib2.Request(USER_URL.format(
            urllib2.quote(user_name), CLIENT_ID))
        resp = json.loads(urllib2.urlopen(req).read())
    except:
        return None
    if not resp or 'key' not in resp[0]:
        print_error("Error, user name {} does not exist...".format(user_name))
        return None
    return resp[0]['key']


def get_user_hashes(user_key, upload_token):
    user_permission_hash = ""
    user_signature_hash = ""
    req = urllib2.Request(USER_UPLOAD_URL.format(user_key, CLIENT_ID))
    req.add_header('Authorization', 'Bearer {}'.format(upload_token))
    resp = json.loads(urllib2.urlopen(req).read())
    if 'images_hash' in resp:
        user_signature_hash = resp['images_hash']
    if 'images_policy' in resp:
        user_permission_hash = resp['images_policy']

    return (user_permission_hash, user_signature_hash)


def get_user(jwt):
    req = urllib2.Request(ME_URL)
    req.add_header('Authorization', 'Bearer {}'.format(jwt))
    return json.loads(urllib2.urlopen(req).read())


def upload_done_file(url, permission, signature, key=None, aws_key=None):

    # upload with many attempts to avoid issues
    max_attempts = 100
    s3_filename = "DONE"
    if key is None:
        s3_key = s3_filename
    else:
        s3_key = key + s3_filename

    parameters = {"key": s3_key, "AWSAccessKeyId": aws_key, "acl": "private",
                  "policy": permission, "signature": signature, "Content-Type": "image/jpeg"}

    encoded_string = ''

    data, headers = encode_multipart(
        parameters, {'file': {'filename': s3_filename, 'content': encoded_string}})
    if DRY_RUN == False:
        displayed_upload_error = False
        for attempt in range(max_attempts):
            # Initialize response before each attempt
            response = None
            try:
                request = urllib2.Request(url, data=data, headers=headers)
                response = urllib2.urlopen(request)
                if response.getcode() == 204:
                    if displayed_upload_error == True:
                        print("Successful upload of {} on attempt {}".format(
                            s3_filename, attempt))
                break  # attempts
            except urllib2.HTTPError as e:
                print("HTTP error: {} on {}, will attempt upload again for {} more times".format(
                    e, s3_filename, max_attempts - attempt - 1))
                displayed_upload_error = True
                time.sleep(5)
            except urllib2.URLError as e:
                print("URL error: {} on {}, will attempt upload again for {} more times".format(
                    e, s3_filename, max_attempts - attempt - 1))
                time.sleep(5)
            except httplib.HTTPException as e:
                print("HTTP exception: {} on {}, will attempt upload again for {} more times".format(
                    e, s3_filename, max_attempts - attempt - 1))
                time.sleep(5)
            except OSError as e:
                print("OS error: {} on {}, will attempt upload again for {} more times".format(
                    e, s3_filename, max_attempts - attempt - 1))
                time.sleep(5)
            except socket.timeout as e:
                # Specific timeout handling for Python 2.7
                print("Timeout error: {0}, will attempt upload again for {} more times".format(
                    s3_filename, max_attempts - attempt - 1))
            finally:
                if response is not None:
                    response.close()
    else:
        print('DRY_RUN, Skipping actual DONE file upload. Use this for debug only')


def upload_file(filepath, max_attempts, url, permission, signature, key=None, aws_key=None):
    '''
    Upload file at filepath.

    '''
    if max_attempts == None:
        max_attempts = MAX_ATTEMPTS

    filename = os.path.basename(filepath)

    s3_filename = filename
    try:
        s3_filename = ExifRead(filepath).exif_name()
    except:
        pass

    filepath_keep_original = processing.processed_images_rootpath(filepath)
    filepath_in = filepath
    if os.path.isfile(filepath_keep_original):
        filepath = filepath_keep_original

    # add S3 'path' if given
    if key is None:
        s3_key = s3_filename
    else:
        s3_key = key + s3_filename

    parameters = {"key": s3_key, "AWSAccessKeyId": aws_key, "acl": "private",
                  "policy": permission, "signature": signature, "Content-Type": "image/jpeg"}

    with open(filepath, "rb") as f:
        encoded_string = f.read()

    data, headers = encode_multipart(
        parameters, {'file': {'filename': filename, 'content': encoded_string}})
    if (DRY_RUN == False):
        displayed_upload_error = False
        for attempt in range(max_attempts):
            # Initialize response before each attempt
            response = None
            try:
                request = urllib2.Request(url, data=data, headers=headers)
                response = urllib2.urlopen(request)
                if response.getcode() == 204:
                    create_upload_log(filepath_in, "upload_success")
                    if displayed_upload_error == True:
                        print("Successful upload of {} on attempt {}".format(
                            filename, attempt))
                else:
                    create_upload_log(filepath_in, "upload_failed")
                break  # attempts

            except urllib2.HTTPError as e:
                print("HTTP error: {} on {}, will attempt upload again for {} more times".format(
                    e, filename, max_attempts - attempt - 1))
                displayed_upload_error = True
                time.sleep(5)
            except urllib2.URLError as e:
                print("URL error: {} on {}, will attempt upload again for {} more times".format(
                    e, filename, max_attempts - attempt - 1))
                time.sleep(5)
            except httplib.HTTPException as e:
                print("HTTP exception: {} on {}, will attempt upload again for {} more times".format(
                    e, filename, max_attempts - attempt - 1))
                time.sleep(5)
            except OSError as e:
                print("OS error: {} on {}, will attempt upload again for {} more times".format(
                    e, filename, max_attempts - attempt - 1))
                time.sleep(5)
            except socket.timeout as e:
                # Specific timeout handling for Python 2.7
                print("Timeout error: {} (retrying), will attempt upload again for {} more times".format(
                    filename, max_attempts - attempt - 1))
            finally:
                if response is not None:
                    response.close()
    else:
        print('DRY_RUN, Skipping actual image upload. Use this for debug only.')


def ascii_encode_dict(data):
    def ascii_encode(x): return x.encode('ascii')
    return dict(map(ascii_encode, pair) for pair in data.items())


def upload_file_list_direct(file_list, number_threads=None, max_attempts=None, api_version=1.0):
    # set some uploader params first
    if number_threads == None:
        number_threads = NUMBER_THREADS
    if max_attempts == None:
        max_attempts = MAX_ATTEMPTS

    # create upload queue with all files per sequence
    q = Queue()
    for filepath in file_list:
        q.put((filepath, max_attempts, UPLOAD_PARAMS))
    # create uploader threads
    uploaders = [UploadThread(q) for i in range(number_threads)]

    # start uploaders as daemon threads that can be stopped (ctrl-c)
    try:
        print("Uploading with {} threads".format(number_threads))
        for uploader in uploaders:
            uploader.daemon = True
            uploader.start()

        while q.unfinished_tasks:
            time.sleep(1)
        q.join()
    except (KeyboardInterrupt, SystemExit):
        print("\nBREAK: Stopping upload.")
        sys.exit(1)


def upload_file_list_manual(file_list, file_params, sequence_idx, number_threads=None, max_attempts=None):
    # set some uploader params first
    if number_threads == None:
        number_threads = NUMBER_THREADS
    if max_attempts == None:
        max_attempts = MAX_ATTEMPTS

    # create upload queue with all files per sequence
    q = Queue()
    for filepath in file_list:
        q.put((filepath, max_attempts, file_params[filepath]))
    # create uploader threads
    uploaders = [UploadThread(q) for i in range(number_threads)]

    # start uploaders as daemon threads that can be stopped (ctrl-c)
    try:
        print("Uploading {}. sequence with {} threads".format(
            sequence_idx + 1, number_threads))
        for uploader in uploaders:
            uploader.daemon = True
            uploader.start()

        while q.unfinished_tasks:
            time.sleep(1)
        q.join()
    except (KeyboardInterrupt, SystemExit):
        print("\nBREAK: Stopping upload.")
        sys.exit(1)
    upload_done_file(**file_params[filepath])
    flag_finalization(file_list)


def log_rootpath(filepath):
    return os.path.join(os.path.dirname(filepath), ".mapillary", "logs", os.path.splitext(os.path.basename(filepath))[0])


def create_upload_log(filepath, status):
    upload_log_root = log_rootpath(filepath)
    upload_log_filepath = os.path.join(upload_log_root, status)
    upload_opposite_log_filepath = os.path.join(
        upload_log_root, UPLOAD_STATUS_PAIRS[status])
    if not os.path.isdir(upload_log_root):
        os.makedirs(upload_log_root)
        open(upload_log_filepath, "w").close()
        open(upload_log_filepath + "_" +
             str(time.strftime("%Y_%m_%d_%H_%M_%S", time.gmtime())), "w").close()
    else:
        if not os.path.isfile(upload_log_filepath):
            open(upload_log_filepath, "w").close()
            open(upload_log_filepath + "_" +
                 str(time.strftime("%Y_%m_%d_%H_%M_%S", time.gmtime())), "w").close()
        if os.path.isfile(upload_opposite_log_filepath):
            os.remove(upload_opposite_log_filepath)

    decoded_filepath = force_decode(filepath)

    ipc.send(
        'upload',
        {
            'image': decoded_filepath,
            'status': 'success' if status == 'upload_success' else 'failed',
        })


# TODO change this, to summarize the upload.log and the processing.log
# maybe, now only used in upload_wth_preprocessing
def upload_summary(file_list, total_uploads, split_groups, duplicate_groups, missing_groups):
    total_success = len([f for f in file_list if 'success' in f])
    total_failed = len([f for f in file_list if 'failed' in f])
    lines = []
    if duplicate_groups:
        lines.append('Duplicates (skipping):')
        lines.append('  groups:       {}'.format(len(duplicate_groups)))
        lines.append('  total:        {}'.format(
            sum([len(g) for g in duplicate_groups])))
    if missing_groups:
        lines.append('Missing Required EXIF (skipping):')
        lines.append('  total:        {}'.format(
            sum([len(g) for g in missing_groups])))

    lines.append('Sequences:')
    lines.append('  groups:       {}'.format(len(split_groups)))
    lines.append('  total:        {}'.format(
        sum([len(g) for g in split_groups])))
    lines.append('Uploads:')
    lines.append('  total uploads this run: {}'.format(total_uploads))
    lines.append('  total:        {}'.format(total_success + total_failed))
    lines.append('  success:      {}'.format(total_success))
    lines.append('  failed:       {}'.format(total_failed))
    lines = '\n'.join(lines)
    return lines


def filter_video_before_upload(video,filter_night_time=False):
    if not get_blackvue_info(video)['is_Blackvue_video']:
        print("ERROR: Direct video upload is currently only supported for Blackvue DRS900S camera. Please use video_process command for other camera files")
        return True
    if get_blackvue_info(video)['camera_direction']!='Front':
        print("ERROR: Currently, only front Blackvue videos are supported on this command. Please use video_process command for Back videos")
        return True
    [gpx_file_path, isStationaryVid] = gpx_from_blackvue(
            video, use_nmea_stream_timestamp=False)
    video_start_time = get_video_start_time_blackvue(video)

    if isStationaryVid:
        if not gpx_file_path:
            if os.path.basename(os.path.dirname(video)) != 'no_gps_data':
                no_gps_folder = os.path.dirname(video) + '/no_gps_data/'
                if not os.path.exists(no_gps_folder):
                    os.mkdir(no_gps_folder)
                os.rename(video, no_gps_folder + os.path.basename(video))
            print(
                "Skipping file {} due to file not containing gps data".format(video))
            return True
        if os.path.basename(os.path.dirname(video)) != 'stationary':
            stationary_folder = os.path.dirname(video) + '/stationary/'
            if not os.path.exists(stationary_folder):
                os.mkdir(stationary_folder)
            os.rename(video, stationary_folder + os.path.basename(video))
            os.rename(gpx_file_path, stationary_folder +
                        os.path.basename(gpx_file_path))
        print("Skipping file {} due to camera being stationary".format(video))
        return True

    if not isStationaryVid:
        gpx_points = get_points_from_bv(video)
        gps_video_start_time = gpx_points[0][0]
        if filter_night_time == True:
            # Unsupported feature: Check if video was taken at night
            # TODO: Calculate sun incidence angle and decide based on threshold angle
            sunrise_time = 9
            sunset_time = 18
            try:
                timeZoneName, local_timezone_offset = get_timezone_and_utc_offset(
                    gpx_points[0][1], gpx_points[0][2])
                if timeZoneName is None:
                    print("Could not determine local time. Video will be uploaded")
                    return False
                local_video_datetime = video_start_time + local_timezone_offset
                if local_video_datetime.time() < datetime.time(sunrise_time, 0, 0) or local_video_datetime.time() > datetime.time(sunset_time, 0, 0):
                    if os.path.basename(os.path.dirname(video)) != 'nighttime':
                        night_time_folder = os.path.dirname(
                            video) + '/nighttime/'
                    if not os.path.exists(night_time_folder):
                        os.mkdir(night_time_folder)
                    os.rename(video, night_time_folder +
                                os.path.basename(video))
                    os.rename(gpx_file_path, night_time_folder +
                                os.path.basename(gpx_file_path))
                    print(
                        "Skipping file {} due to video being recorded at night (Before 9am or after 6pm)".format(video))
                    return True
            except Exception as e:
                print(
                    "Unable to determine time of day. Exception raised: {} \n Video will be uploaded".format(e))
        return False
def send_videos_for_processing(video_import_path, user_name, user_email=None, user_password=None, verbose=False, skip_subfolders=False, number_threads=None, max_attempts=None, organization_username=None, organization_key=None, private=False, master_upload=False, sampling_distance=2, filter_night_time=False):
    # safe checks
    if not os.path.isdir(video_import_path) and not (os.path.isfile(video_import_path) and video_import_path.lower().endswith("mp4")):
        print("video import path {} does not exist or is invalid, exiting...".format(
            video_import_path))
        sys.exit(1)
    # User Authentication
    credentials = None
    if user_email and user_password:
        credentials = authenticate_with_email_and_pwd(user_email,user_password)
    else:
        try:
            credentials = authenticate_user(user_name)
        except:
            pass
        if credentials == None or "user_upload_token" not in credentials or "user_permission_hash" not in credentials or "user_signature_hash" not in credentials:
            print("Error, user authentication failed for user " + user_name)
            sys.exit(1)

    user_permission_hash = credentials["user_permission_hash"]
    user_signature_hash = credentials["user_signature_hash"]

    response = get_upload_url(credentials)
    request_params = response['videos']

    # upload all videos in the import path
    # get a list of all videos first
    all_videos = get_video_file_list(video_import_path, skip_subfolders) if os.path.isdir(
        video_import_path) else [video_import_path]
    all_videos = [x for x in all_videos if os.path.basename(
        os.path.dirname(x)) != 'uploaded']  # Filter already uploaded videos
    all_videos = [x for x in all_videos if os.path.basename(
        os.path.dirname(x)) != 'stationary']
    all_videos = [x for x in all_videos if os.path.basename(
        os.path.dirname(x)) != 'no_gps_data']
    all_videos = [x for x in all_videos if os.path.basename(
        os.path.dirname(x)) != 'nighttime']

    if max_attempts == None:
        max_attempts = MAX_ATTEMPTS

    for video in tqdm(all_videos, desc="Uploading videos for processing"):
        print("Preparing video {} for upload".format(os.path.basename(video)))
        if not filter_video_before_upload(video,filter_night_time):
            video_start_time = get_video_start_time_blackvue(video)
            # Correct timestamp in case camera time zone is not set correctly. If timestamp is not UTC, sync with GPS track will fail.
            # Only hours are corrected, so that second offsets are taken into
            # account correctly
            gpx_points = get_points_from_bv(video)
            gps_video_start_time = gpx_points[0][0]
            delta_t = video_start_time - gps_video_start_time
            if delta_t.days > 0:
                hours_diff_to_utc = round(delta_t.total_seconds() / 3600)
            else:
                hours_diff_to_utc = round(delta_t.total_seconds() / 3600) * -1
            video_start_time_utc = video_start_time + \
                datetime.timedelta(hours=hours_diff_to_utc)
            video_start_timestamp = int(
                (((video_start_time_utc - datetime.datetime(1970, 1, 1)).total_seconds())) * 1000)
            upload_video_for_processing(
                video, video_start_timestamp, max_attempts, credentials, user_permission_hash, user_signature_hash, request_params, organization_username, organization_key, private, master_upload, sampling_distance)

    print("Upload completed")


def upload_video_for_processing(video, video_start_time, max_attempts, credentials, permission, signature, parameters, organization_username, organization_key, private, master_upload, sampling_distance):
    filename = os.path.basename(video)
    basename = os.path.splitext(filename)[0]
    gpx_path = "{}/{}.gpx".format(os.path.dirname(video), basename)

    if not os.path.exists(os.path.dirname(video) + '/uploaded/'):
        os.mkdir(os.path.dirname(video) + '/uploaded/')

    with open(video, "rb") as f:
        encoded_string = f.read()
    filename_no_ext, file_extension = os.path.splitext(filename)
    path = os.path.dirname(video)
    parameters["fields"]["key"] = "{}/uploads/videos/blackvue/{}/{}".format(
        credentials["MAPSettingsUserKey"], filename_no_ext, filename)

    data = dict(
        parameters=dict(
            organization_key=organization_key,
            private=private,
            images_upload_v2=True,
            make='Blackvue',
            model='DR900S-1CH',
            sample_interval_distance=float(sampling_distance),
            video_start_time=video_start_time
        )
    )
    if master_upload != None:
        data['parameters']['user_key'] = master_upload

    if not DRY_RUN:
        print("Uploading...")
        for attempt in range(max_attempts):
            # Initialize response before each attempt
            response = None
            try:
                files = {"file": encoded_string}
                response = requests.post(
                    parameters["url"], data=parameters["fields"], files=files)
                if response.status_code == '204':
                    create_upload_log(video, "upload_success")
                break
            except requests.exceptions.HTTPError as e:
                print("Upload error: {} on {}, will attempt to upload again for {} more times".format(e, filename, max_attempts - attempt - 1))
                time.sleep(5)
            except requests.exceptions.ConnectionError as e:
                print("Upload error: {} on {}, will attempt to upload again for {} more times".format(e, filename, max_attempts - attempt - 1))
                time.sleep(5)
            finally:
                if response is not None:
                    response.close()
        # Upload Done file
        with open("{}/DONE".format(path), 'w') as outfile:
            yaml.dump(data, outfile, default_flow_style=False)

            with open("{}/DONE".format(path), "rb") as f:
                encoded_string = f.read()
            parameters["fields"]["key"] = "{}/uploads/videos/blackvue/{}/DONE".format(
                credentials["MAPSettingsUserKey"], filename_no_ext, filename)

            for attempt in range(max_attempts):
                # Initialize response before each attempt
                response = None
                try:
                    files = {"file": encoded_string}
                    response = requests.post(
                        parameters["url"], data=parameters["fields"], files=files)
                    os.rename(video, os.path.dirname(video) +
                              '/uploaded/' + os.path.basename(video))
                    os.rename(gpx_path, os.path.dirname(video) +
                              '/uploaded/' + os.path.basename(gpx_path))
                    print("Uploaded {} successfully".format(os.path.basename(video)))
                    break
                except requests.exceptions.HTTPError as e:
                    print("Upload error: {} on {}, will attempt to upload again for {} more times".format(e, filename, max_attempts - attempt - 1))
                    time.sleep(5)
                except requests.exceptions.ConnectionError as e:
                    print("Upload error: {} on {}, will attempt to upload again for {} more times".format(e, filename, max_attempts - attempt - 1))
                    time.sleep(5)
                finally:
                    if response is not None:
                        response.close()
    else:
        print('DRY_RUN, Skipping actual video upload. Use this for debug only.')
