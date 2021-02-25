import os
import sys

from . import api_v3
from . import config
from . import uploader

"""
(re)authenticate
"""
GLOBAL_CONFIG_FILEPATH = os.getenv(
    "GLOBAL_CONFIG_FILEPATH",
    os.path.join(
        os.path.expanduser("~"), ".config", "mapillary", "configs", api_v3.CLIENT_ID
    ),
)


def edit_config(
    config_file=None,
    user_name=None,
    user_email=None,
    user_password=None,
    jwt=None,
    force_overwrite=False,
    user_key=None,
):
    if config_file is None:
        config_file = GLOBAL_CONFIG_FILEPATH

    if not os.path.isfile(config_file):
        config.create_config(config_file)

    if jwt:
        user = api_v3.get_user(jwt)
        user_items = {
            "MAPSettingsUsername": user["username"],
            "MAPSettingsUserKey": user["key"],
            "user_upload_token": jwt,
        }
        config.update_config(config_file, user["username"], user_items)
        return

    if user_key and user_name:  # Manually add user_key
        user_items = {
            "MAPSettingsUsername": "Dummy_MAPSettingsUsername",
            "MAPSettingsUserKey": user_key,
            "user_upload_token": "Dummy_upload_token",
        }
        config.update_config(config_file, user_name, user_items)
        return

    # config file must exist at this step
    # load
    config_object = config.load_config(config_file)

    if not user_name:
        user_name = input(
            "Enter the Mapillary user name you would like to (re)authenticate: "
        )

    # safety check if section exists, otherwise add it
    if user_name in config_object.sections():
        if not force_overwrite:
            print("Warning, user name exists with the following items : ")
            print(config.load_user(config_object, user_name))
            sure = input(
                "Are you sure you would like to re-authenticate (current parameters will be overwritten) [y,Y,yes,Yes]? "
            )
            if sure not in ["y", "Y", "yes", "Yes"]:
                print(
                    f"Aborting re-authentication. If you would like to re-authenticate user name {user_name}, rerun this command and confirm re-authentication."
                )
                return
    else:
        config_object.add_section(user_name)

    if user_email and user_password:
        user_key = api_v3.get_user_key(user_name)
        if not user_key:
            print(
                f"User name {user_name} does not exist, please try again or contact Mapillary user support."
            )
            sys.exit(1)
        upload_token = api_v3.get_upload_token(user_email, user_password)
        if not upload_token:
            print(f"Authentication failed for user name {user_name}, please try again.")
            sys.exit(1)
        user_items = {
            "MAPSettingsUsername": user_name,
            "MAPSettingsUserKey": user_key,
            "user_upload_token": upload_token,
        }
    else:
        # fill in the items and save
        user_items = uploader.prompt_user_for_user_items(user_name)
        if not user_items:
            print(f"Authentication failed for user name {user_name}, please try again.")
            sys.exit(1)

    config.update_config(config_file, user_name, user_items)
