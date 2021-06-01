import getpass
import os
from typing import Optional, Dict

from . import MAPILLARY_API_VERSION, api_v3, api_v4, config
from .config import GLOBAL_CONFIG_FILEPATH


def prompt_user_for_user_items(user_name: str) -> Optional[dict]:
    print(f"Enter user credentials for user {user_name}:")
    user_email = input("Enter email: ")
    user_password = getpass.getpass("Enter user password: ")

    if MAPILLARY_API_VERSION == "v3":
        user_key = api_v3.get_user_key(user_name)
        if not user_key:
            return None
        upload_token = api_v3.get_upload_token(user_email, user_password)
    else:
        assert MAPILLARY_API_VERSION == "v4"
        data = api_v4.get_upload_token(user_email, user_password)
        upload_token = data.get("access_token")
        user_key = data.get("user_id")

    if not upload_token:
        return None

    return {
        "MAPSettingsUsername": user_name,
        "MAPSettingsUserKey": user_key,
        "user_upload_token": upload_token,
    }


def authenticate_user(user_name: str) -> Optional[Dict]:
    if os.path.isfile(GLOBAL_CONFIG_FILEPATH):
        global_config_object = config.load_config(GLOBAL_CONFIG_FILEPATH)
        if user_name in global_config_object.sections():
            return config.load_user(global_config_object, user_name)

    user_items = prompt_user_for_user_items(user_name)
    if not user_items:
        return None

    config.create_config(GLOBAL_CONFIG_FILEPATH)
    config.update_config(GLOBAL_CONFIG_FILEPATH, user_name, user_items)
    return user_items


def get_master_key() -> str:
    master_key = ""
    if os.path.isfile(GLOBAL_CONFIG_FILEPATH):
        global_config_object = config.load_config(GLOBAL_CONFIG_FILEPATH)
        if "MAPAdmin" in global_config_object.sections():
            admin_items = config.load_user(global_config_object, "MAPAdmin")
            if "MAPILLARY_SECRET_HASH" in admin_items:
                master_key = admin_items["MAPILLARY_SECRET_HASH"]
            else:
                create_config = input(
                    "Master upload key does not exist in your global Mapillary config file, set it now?"
                )
                if create_config in ["y", "Y", "yes", "Yes"]:
                    master_key = set_master_key()
        else:
            create_config = input(
                "MAPAdmin section not in your global Mapillary config file, set it now? "
            )
            if create_config in ["y", "Y", "yes", "Yes"]:
                master_key = set_master_key()
    else:
        create_config = input(
            "Master upload key needs to be saved in the global Mapillary config file, which does not exist, create one now? "
        )
        if create_config in ["y", "Y", "yes", "Yes"]:
            config.create_config(GLOBAL_CONFIG_FILEPATH)
            master_key = set_master_key()

    return master_key


def set_master_key() -> str:
    config_object = config.load_config(GLOBAL_CONFIG_FILEPATH)
    section = "MAPAdmin"
    if section not in config_object.sections():
        config_object.add_section(section)
    master_key = input("Enter the master key: ")
    if master_key != "":
        config_object = config.set_user_items(
            config_object, section, {"MAPILLARY_SECRET_HASH": master_key}
        )
        config.save_config(config_object, GLOBAL_CONFIG_FILEPATH)
    return master_key
