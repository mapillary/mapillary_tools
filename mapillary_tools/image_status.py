import BTrees.OOBTree
import ZODB, ZODB.FileStorage
import transaction
import os

# Globals
initiated = False

storage = None
db = None
connection = None
dbRoot = None

def initiate_storage(import_path,
                     user_name,
                     organization_username=None,
                     organization_key=None,
                     private=False,
                     master_upload=False,
                     verbose=False,
                     rerun=False,
                     skip_subfolders=False,
                     video_import_path=None):
    global initiated

    global storage
    global db
    global connection
    global dbRoot

    if initiated:
        return
    initiated = True

    storage = ZODB.FileStorage.FileStorage(os.path.join(import_path, ".mapillary_status.fs"))
    # storage = ZODB.FileStorage.FileStorage("performance.ts")
    db = ZODB.DB(storage)
    connection = db.open()
    dbRoot = connection.root

    if not hasattr(dbRoot, 'image_statuses'):
        dbRoot.image_statuses = BTrees.OOBTree.BTree()
        transaction.commit()

    all_files = []
    all_files_dict = {}

    if skip_subfolders:
        all_files.extend(os.path.join(os.path.abspath(root_dir), file) for file in os.listdir(root_dir) if file.lower().endswith(
            ('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')) and preform_process(os.path.join(root_dir, file), process, rerun))
    else:
        for root, dirs, files in os.walk(import_path, topdown=True):
            # Exclude log directories
            dirs[:] = [d for d in dirs if d not in [".mapillary", "logs"]]

            for file in files:
                # FIXME CHECK PREFORM PROCESS
                if file.lower().endswith(('jpg', 'jpeg', 'tif', 'tiff', 'pgm', 'pnm', 'gif')):
                    all_files.append(os.path.join(os.path.abspath(root), file))

    for file in all_files:
        all_files_dict[file] = True

    for key in list(dbRoot.image_statuses.keys()):
        if key not in all_files_dict:
            dbRoot.image_statuses.pop(key)

    for file in all_files:
        if file not in dbRoot.image_statuses:
            dbRoot.image_statuses[file] = BTrees.OOBTree.BTree()

    transaction.commit()

#def preform_process(file_path, process, rerun=False):
#    log_root = uploader.log_rootpath(file_path)
#    process_succes = os.path.join(log_root, process + "_success")
#    upload_succes = os.path.join(log_root, "upload_success")
#    preform = not os.path.isfile(upload_succes) and (
#        not os.path.isfile(process_succes) or rerun)
#    return preform

def get_all_files():
    global dbRoot
    return dbRoot.keys()

def get_keys_with_status(setting, excluded_value):
    global dbRoot

    ret_files = []

    for key, value in dbRoot.image_statuses.items():
        if value.get(setting, None) != excluded_value:
            ret_files.append(key)

    return ret_files

def get_keys_with_status_fixme(setting, success_value):
    global dbRoot

    ret_files = []

    for key, value in dbRoot.image_statuses.items():
        dbValue = value.get(setting, 0)
        if success_value == "success" and dbValue == 1:
            ret_files.append(key)
        if success_value == "failed" and dbValue == 0:
            ret_files.append(key)

    return ret_files

def set_value(file, key, status, transact=True):
    global dbRoot
    dbRoot.image_statuses[file][key] = status
    if transact:
        transaction.commit()

def get_value(file, key, default=None):
    global dbRoot
    return dbRoot.image_statuses[file].get(key, default)

def transact():
    transaction.commit()
