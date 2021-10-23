import configparser
import os
import typing as T

from . import api_v4, types


_CLIENT_ID = api_v4.MAPILLARY_CLIENT_TOKEN
# Windows is not happy with | so we convert MLY|ID|TOKEN to MLY_ID_TOKEN
_CLIENT_ID = _CLIENT_ID.replace("|", "_", 2)

DEFAULT_MAPILLARY_FOLDER = os.path.join(
    os.path.expanduser("~"),
    ".config",
    "mapillary",
)

MAPILLARY_CONFIG_PATH = os.getenv(
    "MAPILLARY_CONFIG_PATH",
    os.path.join(
        DEFAULT_MAPILLARY_FOLDER,
        "configs",
        _CLIENT_ID,
    ),
)


def load_config(config_path: str) -> configparser.ConfigParser:
    if not os.path.isfile(config_path):
        raise RuntimeError(f"config {config_path} does not exist")
    config = configparser.ConfigParser()
    config.optionxform = str  # type: ignore
    config.read(config_path)
    return config


def save_config(config: configparser.ConfigParser, config_path: str) -> None:
    with open(config_path, "w") as cfg:
        config.write(cfg)


def load_user(config: configparser.ConfigParser, user_name: str) -> types.UserItem:
    user_items = dict(config.items(user_name))
    return T.cast(types.UserItem, user_items)


def add_user(
    config: configparser.ConfigParser, user_name: str, config_path: str
) -> None:
    if user_name not in config.sections():
        config.add_section(user_name)
    else:
        print(f"Error, user {user_name} already exists")
    save_config(config, config_path)


def set_user_items(
    config: configparser.ConfigParser, user_name: str, user_items: types.UserItem
) -> configparser.ConfigParser:
    for key, val in user_items.items():
        config.set(user_name, key, T.cast(str, val))
    return config


def update_config(config_path: str, user_name: str, user_items: types.UserItem) -> None:
    config = load_config(config_path)
    if user_name not in config.sections():
        add_user(config, user_name, config_path)
    config = set_user_items(config, user_name, user_items)
    save_config(config, config_path)


def create_config(config_path: str) -> None:
    if not os.path.isdir(os.path.dirname(config_path)):
        os.makedirs(os.path.dirname(config_path))
    open(config_path, "a").close()
