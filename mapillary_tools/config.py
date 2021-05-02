import configparser
import os

from . import api_v3, api_v4, MAPILLARY_API_VERSION


GLOBAL_CONFIG_FILEPATH = os.getenv(
    "GLOBAL_CONFIG_FILEPATH",
    os.path.join(
        os.path.expanduser("~/.config/mapillary/configs"),
        api_v3.MAPILLARY_WEB_CLIENT_ID
        if MAPILLARY_API_VERSION == "v3"
        else api_v4.MAPILLARY_WEB_CLIENT_ID,
    ),
)


def load_config(config_path):
    config = None
    if os.path.isfile(config_path):
        config = configparser.ConfigParser()
        try:
            config.optionxform = str
            config.read(config_path)
        except:
            print("Error reading config file")
    else:
        print("Error, config file does not exist")
    return config


def save_config(config, config_path):
    with open(config_path, "w") as cfg:
        try:
            config.write(cfg)
        except:
            print("Error writing config file")


def load_user(config, user_name):
    user_items = None
    try:
        user_items = dict(config.items(user_name))
    except:
        print("Error loading user credentials")
    return user_items


def add_user(config, user_name, config_path):
    if user_name not in config.sections():
        try:
            config.add_section(user_name)
        except:
            print("Error adding new user section, for user_name " + user_name)
    else:
        print("Error, user " + user_name + " already exists")
    save_config(config, config_path)


def set_user_items(config, user_name, user_items):
    for key in user_items.keys():
        try:
            config.set(user_name, key, user_items[key])
        except:
            print(
                "Error setting config key "
                + key
                + " with value "
                + str(user_items[key])
                + " for user_name "
                + user_name
            )
    return config


def update_config(config_path, user_name, user_items):
    config = load_config(config_path)
    if user_name not in config.sections():
        add_user(config, user_name, config_path)
    config = set_user_items(config, user_name, user_items)
    save_config(config, config_path)


def create_config(config_path):
    if not os.path.isdir(os.path.dirname(config_path)):
        os.makedirs(os.path.dirname(config_path))
    open(config_path, "a").close()
