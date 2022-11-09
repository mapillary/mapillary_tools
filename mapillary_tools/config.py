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


def _load_config(config_path: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    # Override to not change option names (by default it will lower them)
    config.optionxform = str  # type: ignore
    # If path not found, then config will be empty
    config.read(config_path)
    return config


def load_user(
    user_name: str, config_path: T.Optional[str] = None
) -> T.Optional[types.UserItem]:
    if config_path is None:
        config_path = MAPILLARY_CONFIG_PATH
    config = _load_config(config_path)
    if not config.has_section(user_name):
        return None
    user_items = dict(config.items(user_name))
    return T.cast(types.UserItem, user_items)


def list_all_users(config_path: T.Optional[str] = None) -> T.List[types.UserItem]:
    if config_path is None:
        config_path = MAPILLARY_CONFIG_PATH
    cp = _load_config(config_path)
    users = [
        load_user(user_name, config_path=config_path) for user_name in cp.sections()
    ]
    return [item for item in users if item is not None]


def update_config(
    user_name: str, user_items: types.UserItem, config_path: T.Optional[str] = None
) -> None:
    if config_path is None:
        config_path = MAPILLARY_CONFIG_PATH
    config = _load_config(config_path)
    if not config.has_section(user_name):
        config.add_section(user_name)
    for key, val in user_items.items():
        config.set(user_name, key, T.cast(str, val))
    os.makedirs(os.path.dirname(os.path.abspath(config_path)), exist_ok=True)
    with open(config_path, "w") as fp:
        config.write(fp)
