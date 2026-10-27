# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import configparser
import errno
import logging
import os
import shutil
import sys
import tempfile
import typing as T
from typing import TypedDict

import jsonschema

if sys.version_info >= (3, 11):
    from typing import Required
else:
    from typing_extensions import Required

from . import api_v4


LOG = logging.getLogger(__name__)

DEFAULT_MAPILLARY_FOLDER = os.path.join(os.path.expanduser("~"), ".config", "mapillary")
MAPILLARY_CONFIG_PATH = os.getenv(
    "MAPILLARY_CONFIG_PATH",
    os.path.join(
        DEFAULT_MAPILLARY_FOLDER,
        "configs",
        # Windows is not happy with | so we convert MLY|ID|TOKEN to MLY_ID_TOKEN
        api_v4.MAPILLARY_CLIENT_TOKEN.replace("|", "_"),
    ),
)


class UserItem(TypedDict, total=False):
    MAPOrganizationKey: int | str
    # Username
    MAPSettingsUsername: str
    # User ID
    MAPSettingsUserKey: str
    # User access token
    user_upload_token: Required[str]


UserItemSchema = {
    "type": "object",
    "properties": {
        "MAPOrganizationKey": {"type": ["integer", "string"]},
        # Not in use. Keep here for back-compatibility
        "MAPSettingsUsername": {"type": "string"},
        "MAPSettingsUserKey": {"type": "string"},
        "user_upload_token": {"type": "string"},
    },
    "required": ["user_upload_token"],
    "additionalProperties": True,
}


UserItemSchemaValidator = jsonschema.Draft202012Validator(UserItemSchema)


# A saved organization name is a line "MAPOrganization.NAME = ID" in its profile's
# section. It is not MAPOrganizationKey: that one makes every upload of the profile
# go to the organization
ORGANIZATION_OPTION_PREFIX = "MAPOrganization."


def _load_config(config_path: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    # Override to not change option names (by default it will lower them)
    config.optionxform = str  # type: ignore
    # If path not found, then config will be empty
    config.read(config_path)
    return config


def load_user(profile_name: str, config_path: str | None = None) -> UserItem | None:
    if config_path is None:
        config_path = MAPILLARY_CONFIG_PATH
    config = _load_config(config_path)
    if not config.has_section(profile_name):
        return None
    user_items = dict(config.items(profile_name))
    return T.cast(UserItem, user_items)


def list_all_users(config_path: str | None = None) -> dict[str, UserItem]:
    if config_path is None:
        config_path = MAPILLARY_CONFIG_PATH
    cp = _load_config(config_path)
    users = {
        profile_name: load_user(profile_name, config_path=config_path)
        for profile_name in cp.sections()
    }
    return {profile: item for profile, item in users.items() if item is not None}


def update_config(
    profile_name: str, user_items: UserItem, config_path: str | None = None
) -> None:
    if config_path is None:
        config_path = MAPILLARY_CONFIG_PATH
    config = _load_config(config_path)
    if not config.has_section(profile_name):
        config.add_section(profile_name)
    for key, val in user_items.items():
        config.set(profile_name, key, T.cast(str, val))
    _write_config(config, config_path)


def remove_config(profile_name: str, config_path: str | None = None) -> None:
    if config_path is None:
        config_path = MAPILLARY_CONFIG_PATH

    config = _load_config(config_path)
    if not config.has_section(profile_name):
        return

    config.remove_section(profile_name)

    _write_config(config, config_path)


def list_organizations(user_items: UserItem) -> dict[str, str]:
    """
    Return the organization names saved in a profile, mapped to their IDs
    """
    return {
        key[len(ORGANIZATION_OPTION_PREFIX) :]: str(val)
        for key, val in user_items.items()
        if key.startswith(ORGANIZATION_OPTION_PREFIX)
    }


def save_organization(
    profile_name: str,
    organization_name: str,
    organization_id: str,
    config_path: str | None = None,
) -> None:
    if config_path is None:
        config_path = MAPILLARY_CONFIG_PATH
    config = _load_config(config_path)
    config.set(
        profile_name, ORGANIZATION_OPTION_PREFIX + organization_name, organization_id
    )
    _write_config(config, config_path)


def remove_organization(
    profile_name: str, organization_name: str, config_path: str | None = None
) -> bool:
    """
    Remove a saved organization name from a profile.
    Return False if the profile has no such name
    """
    if config_path is None:
        config_path = MAPILLARY_CONFIG_PATH
    config = _load_config(config_path)
    if not config.has_section(profile_name):
        return False
    if not config.remove_option(
        profile_name, ORGANIZATION_OPTION_PREFIX + organization_name
    ):
        return False
    _write_config(config, config_path)
    return True


def _write_config(config: configparser.ConfigParser, config_path: str) -> None:
    # Write where a symlinked config points, and keep the link
    config_path = os.path.realpath(config_path)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    try:
        _replace_config(config, config_path)
    except OSError as ex:
        # A folder that does not allow creating files, a config file mounted into
        # a container (EBUSY), or on Windows, a config that another process has open
        if not isinstance(ex, PermissionError) and ex.errno != errno.EBUSY:
            raise
        LOG.debug("Writing the config %s in place: %s", config_path, ex)
        with open(config_path, "w") as fp:
            config.write(fp)


def _replace_config(config: configparser.ConfigParser, config_path: str) -> None:
    # Write a temporary file and replace the config with it, so that a process
    # reading the config at the same time never sees it half written
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(config_path),
        prefix=os.path.basename(config_path) + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as fp:
            config.write(fp)
            fp.flush()
            os.fsync(fp.fileno())
        if os.path.exists(config_path):
            # mkstemp creates the file readable by its owner only
            shutil.copymode(config_path, tmp_path)
        os.replace(tmp_path, config_path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
