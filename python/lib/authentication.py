import config
import os

# template for the future authenticate function to be put in the uploader.py

LOCAL_CONFIG_FILEPATH = os.path.join(
    os.path.expanduser('~'), '{}.mapillary/config')
GLOBAL_CONFIG_FILEPATH = os.path.expanduser('~/.config/mapillary/config')


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
