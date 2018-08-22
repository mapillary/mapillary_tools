from exif_read import ExifRead
import json
import os
import string
import threading
import sys
import urllib2
import urllib
import httplib
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

MAPILLARY_UPLOAD_URL = "https://d22zcsn13kp53w.cloudfront.net/"
MAPILLARY_DIRECT_UPLOAD_URL = "https://s3-eu-west-1.amazonaws.com/mapillary.uploads.images"
PERMISSION_HASH = "eyJleHBpcmF0aW9uIjoiMjAyMC0wMS0wMVQwMDowMDowMFoiLCJjb25kaXRpb25zIjpbeyJidWNrZXQiOiJtYXBpbGxhcnkudXBsb2Fkcy5pbWFnZXMifSxbInN0YXJ0cy13aXRoIiwiJGtleSIsIiJdLHsiYWNsIjoicHJpdmF0ZSJ9LFsic3RhcnRzLXdpdGgiLCIkQ29udGVudC1UeXBlIiwiIl0sWyJjb250ZW50LWxlbmd0aC1yYW5nZSIsMCwyMDQ4NTc2MF1dfQ=="
SIGNATURE_HASH = "f6MHj3JdEq8xQ/CmxOOS7LvMxoI="
BOUNDARY_CHARS = string.digits + string.ascii_letters
NUMBER_THREADS = int(os.getenv('NUMBER_THREADS', '4'))
MAX_ATTEMPTS = int(os.getenv('MAX_ATTEMPTS', '10'))
UPLOAD_PARAMS = {"url": MAPILLARY_UPLOAD_URL, "permission": PERMISSION_HASH,
                 "signature": SIGNATURE_HASH, "aws_key": "AKIAI2X3BJAT2W75HILA"}
CLIENT_ID = "MkJKbDA0bnZuZlcxeTJHTmFqN3g1dzo1YTM0NjRkM2EyZGU5MzBh"
LOGIN_URL = "https://a.mapillary.com/v2/ua/login?client_id={}".format(
    CLIENT_ID)
ORGANIZATIONS_URL = "https://a.mapillary.com/v3/users/{}/organizations?client_id={}"
USER_URL = "https://a.mapillary.com/v3/users?usernames={}&client_id={}"
ME_URL = "https://a.mapillary.com/v3/me?client_id={}".format(CLIENT_ID)
USER_UPLOAD_URL = "https://a.mapillary.com/v3/users/{}/upload_tokens?client_id={}"
UPLOAD_STATUS_PAIRS = {"upload_success": "upload_failed",
                       "upload_failed": "upload_success"}
GLOBAL_CONFIG_FILEPATH = os.path.join(
    os.path.expanduser('~'), ".config", "mapillary", 'config')


class UploadThread(threading.Thread):
    def __init__(self, queue):
        threading.Thread.__init__(self)
        self.q = queue
        self.total_task = self.q.qsize()

    def run(self):
        while True:
            # fetch file from the queue and upload
            filepath, params = self.q.get()
            if filepath is None:
                self.q.task_done()
                break
            else:
                progress(self.total_task - self.q.qsize(), self.total_task,
                         '... {} images left.'.format(self.q.qsize()))
                upload_file(filepath, **params)
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


def process_upload_finalization(file_list, params):
    list_params = []
    keys = []
    for file in file_list:
        if file in params:
            if params[file]["key"] not in keys:
                keys.append(params[file]["key"])
                list_params.append(params[file])
    return list_params


def finalize_upload(import_path, finalize_params):
    for params in finalize_params:
        upload_done_file(import_path, params)


def flag_finalization(finalize_file_list):
    for file in finalize_file_list:
        finalize_flag = os.path.join(log_rootpath(file), "upload_finalized")
        open(finalize_flag, 'a').close()


def get_upload_file_list(import_path, skip_subfolders=False):
    upload_file_list = []
    if skip_subfolders:
        upload_file_list.extend(os.path.join(import_path, file) for file in os.listdir(import_path) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and preform_upload(import_path, file))
    else:
        for root, dir, files in os.walk(import_path):
            if ".mapillary" in root:
                continue
            upload_file_list.extend(os.path.join(root, file) for file in files if file.lower().endswith(
                ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and preform_upload(root, file))
    return sorted(upload_file_list)


def get_total_file_list(import_path, skip_subfolders=False):
    total_file_list = []
    if skip_subfolders:
        total_file_list.extend(os.path.join(import_path, file) for file in os.listdir(import_path) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')))
    else:
        for root, dir, files in os.walk(import_path):
            if ".mapillary" in root:
                continue
            total_file_list.extend(os.path.join(root, file) for file in files if file.lower(
            ).endswith(('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')))
    return sorted(total_file_list)


def get_failed_upload_file_list(import_path, skip_subfolders=False):
    failed_upload_file_list = []
    if skip_subfolders:
        failed_upload_file_list.extend(os.path.join(import_path, file) for file in os.listdir(import_path) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and failed_upload(import_path, file))
    else:
        for root, dir, files in os.walk(import_path):
            if ".mapillary" in root:
                continue
            failed_upload_file_list.extend(os.path.join(root, file) for file in files if file.lower(
            ).endswith(('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and failed_upload(root, file))

    return sorted(failed_upload_file_list)


def get_success_upload_file_list(import_path, skip_subfolders=False):
    success_upload_file_list = []
    if skip_subfolders:
        success_upload_file_list.extend(os.path.join(import_path, file) for file in os.listdir(import_path) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and success_upload(import_path, file))
    else:
        for root, dir, files in os.walk(import_path):
            if ".mapillary" in root:
                continue
            success_upload_file_list.extend(os.path.join(root, file) for file in files if file.lower(
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


def preform_upload(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    process_failed = os.path.join(
        log_root, "mapillary_image_description_failed")
    duplicate = os.path.join(log_root, "duplicate")
    upload_succes = os.path.join(log_root, "upload_success")
    upload = not os.path.isfile(
        upload_succes) and not os.path.isfile(process_failed) and not os.path.isfile(
        duplicate)
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
        finalize_file_list.extend(os.path.join(import_path, file) for file in os.listdir(import_path) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and preform_finalize(import_path, file))
    else:
        for root, dir, files in os.walk(import_path):
            if ".mapillary" in root:
                continue
            finalize_file_list.extend(os.path.join(root, file) for file in files if file.lower().endswith(
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
        sys.exit()
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
    sys.exit()


def validate_organization_privacy(user_key, organization_key, private, upload_token):

    call = ORGANIZATIONS_URL.format(user_key, CLIENT_ID)
    req = urllib2.Request(call)
    req.add_header('Authorization', 'Bearer {}'.format(upload_token))
    resp = json.loads(urllib2.urlopen(req).read())

    for org in resp:
        if org['key'] == organization_key:
            if ('private_repository' in org and org['private_repository'] != private) or ('private_repository' not in org and private):
                print(
                    "Organization privacy does not match provided privacy settings.")
                privacy = "private" if 'private_repository' in org and org[
                    'private_repository'] else "public"
                privacy_provided = "private" if private else "public"
                print("Organization " +
                      org['name'] + " with key " + org['key'] + " is " + privacy + " while your import privacy settings state " + privacy_provided)
                sys.exit()


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
    config.create_config(GLOBAL_CONFIG_FILEPATH)
    config.update_config(
        GLOBAL_CONFIG_FILEPATH, user_name, user_items)
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
        req = urllib2.Request(USER_URL.format(user_name, CLIENT_ID))
        resp = json.loads(urllib2.urlopen(req).read())
    except:
        return None
    if not resp or 'key' not in resp[0]:
        print("Error, user name {} does not exist...".format(user_name))
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


def upload_done_file(import_path, params):

    DONE_filepath = os.path.join(import_path, "DONE")

    if not os.path.exists(DONE_filepath):
        open(DONE_filepath, 'a').close()

    # upload
    upload_file(DONE_filepath, **params)

    # remove
    if os.path.exists(DONE_filepath):
        os.remove(DONE_filepath)


def is_done_file(filename):
    return filename == "DONE"


def upload_file(filepath, url, permission, signature, key=None, aws_key=None):
    '''
    Upload file at filepath.

    '''
    filename = os.path.basename(filepath)
    done_file = is_done_file(filename)

    s3_filename = filename
    try:
        if not done_file:
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

    for attempt in range(MAX_ATTEMPTS):

        # Initialize response before each attempt
        response = None

        try:
            request = urllib2.Request(url, data=data, headers=headers)
            response = urllib2.urlopen(request)
            if not done_file:
                if response.getcode() == 204:
                    create_upload_log(filepath_in, "upload_success")
                else:
                    create_upload_log(filepath_in, "upload_failed")
            break  # attempts

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


def ascii_encode_dict(data):
    def ascii_encode(x): return x.encode('ascii')
    return dict(map(ascii_encode, pair) for pair in data.items())


def upload_file_list(file_list, file_params={}):
    # create upload queue with all files
    q = Queue()
    for filepath in file_list:
        if filepath not in file_params:
            q.put((filepath, UPLOAD_PARAMS))
        else:
            q.put((filepath, file_params[filepath]))
    # create uploader threads
    uploaders = [UploadThread(q) for i in range(NUMBER_THREADS)]

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


def log_rootpath(filepath):
    return os.path.join(os.path.dirname(filepath), ".mapillary", "logs", ".".join(os.path.basename(filepath).split(".")[:-1]))


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
