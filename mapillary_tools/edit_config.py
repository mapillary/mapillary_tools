import mapillary_tools.config as config
import os
import sys
import uploader
'''
(re)authenticate
'''

GLOBAL_CONFIG_FILEPATH = os.path.join(
    os.path.expanduser('~'), ".config", "mapillary", 'config')


def edit_config(config_file=None):
    config_file_path = config_file if config_file else GLOBAL_CONFIG_FILEPATH

    if not os.path.isfile(config_file_path):
        create_config = raw_input(
            "Config file " + config_file_path + " does not exist, create one?")
        if create_config in ["y", "Y", "yes", "Yes"]:
            config.create_config(config_file_path)
        else:
            print(
                "Config file to be edited does not exist and is not to be created, exiting...")
            sys.exit()

    # config file must exist at this step
    # load
    config_object = config.load_config(config_file_path)
    # prompt for section
    section = raw_input(
        "Enter the Mapillary user name you would like to (re)authenticate : ")
    # safety check if section exists, otherwise add it
    if section in config_object.sections():
        print("Warning, user name exists with the following items : ")
        print(config.load_user(config_object, section))
        sure = raw_input(
            "Are you sure you would like to re-authenticate[y,Y,yes,Yes]?(current parameters will be overwritten)")
        if sure not in ["y", "Y", "yes", "Yes"]:
            print("Aborting re-authentication. If you would like to re-authenticate user name {}, rerun this command and confirm re-authentication.".format(section))
            sys.exit()
    else:
        config_object.add_section(section)

    # fill in the items and save
    user_items = uploader.prompt_user_for_user_items(section)
    if not user_items:
        print("Authentication failed for user name " +
              section + ", please try again.")
        sys.exit()
    config.update_config(
        config_file_path, section, user_items)
