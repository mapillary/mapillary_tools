import mapillary_tools.config as config
import os
import sys
import uploader
'''
(re)authenticate
'''

GLOBAL_CONFIG_FILEPATH = os.path.join(
    os.path.expanduser('~'), ".config", "mapillary", 'config')


def edit_config(config_file=None, user_name=None, user_email=None, user_password=None, force_overwrite=False):

    config_file_path = config_file if config_file else GLOBAL_CONFIG_FILEPATH

    if not os.path.isfile(config_file_path):
        config.create_config(config_file_path)

    # config file must exist at this step
    # load
    config_object = config.load_config(config_file_path)
    section = user_name
    if not section:
        section = raw_input(
            "Enter the Mapillary user name you would like to (re)authenticate : ")
    # safety check if section exists, otherwise add it
    if section in config_object.sections():
        if not force_overwrite:
            print("Warning, user name exists with the following items : ")
            print(config.load_user(config_object, section))
            sure = raw_input(
                "Are you sure you would like to re-authenticate[y,Y,yes,Yes]?(current parameters will be overwritten)")
            if sure not in ["y", "Y", "yes", "Yes"]:
                print("Aborting re-authentication. If you would like to re-authenticate user name {}, rerun this command and confirm re-authentication.".format(section))
                sys.exit()
    else:
        config_object.add_section(section)

    user_items = {}
    if user_email and user_password:
        user_key = uploader.get_user_key(section)
        if not user_key:
            print("User name {} does not exist, please try again or contact Mapillary user support.".format(
                section))
            sys.exit(1)
        upload_token = uploader.get_upload_token(user_email, user_password)
        if not upload_token:
            print("Authentication failed for user name " +
                  section + ", please try again.")
            sys.exit(1)
        user_permission_hash, user_signature_hash = uploader.get_user_hashes(
            user_key, upload_token)

        user_items["MAPSettingsUsername"] = section
        user_items["MAPSettingsUserKey"] = user_key

        user_items["user_upload_token"] = upload_token
        user_items["user_permission_hash"] = user_permission_hash
        user_items["user_signature_hash"] = user_signature_hash
    else:
        # fill in the items and save
        user_items = uploader.prompt_user_for_user_items(section)
    if not user_items:
        print("Authentication failed for user name " +
              section + ", please try again.")
        sys.exit(1)

    config.update_config(config_file_path, section, user_items)
