import argparse
import mapillary_tools.config as config
import os
import sys
'''
manually edit a config file
'''
parser = argparse.ArgumentParser(
    description='Manually edit a config file')
# path to the config file
parser.add_argument(
    '--config_file', help='Full path to the config file to be edited. Default is ~/.config/mapillary/config', default=None)
args = parser.parse_args()

GLOBAL_CONFIG_FILEPATH = os.path.join(
    os.path.expanduser('~'), ".config", "mapillary", 'config')

config_file_path = args.config_file if args.config_file else GLOBAL_CONFIG_FILEPATH

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
section = raw_input("Section you would like to add/edit : ")
# safety check if section exists, otherwise add it
if section in config_object.sections():
    print("Warning, section exists with the following items : ")
    print(config.load_user(config_object, section))
else:
    config_object.add_section(section)

# fill in the items and save
item_key = ""
item_value = ""
items = {}
print("Adding items in section " + section +
      ", to finish, press d in any separate prompt.")
while (item_key != "d" and item_value != "d"):
    item_key = ""
    item_value = ""

    item_key = raw_input("Add item key : ")
    if item_key != "d":
        item_value = raw_input("Add item value : ")
        if item_value != "d":
            items[item_key] = item_value

if len(items):
    config_object = config.set_user_items(config_object, section, items)
    config.save_config(config_object, config_file_path)
