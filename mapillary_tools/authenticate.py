from __future__ import annotations

import getpass
import json
import logging
import re
import sys
import typing as T

import jsonschema

import requests

from . import api_v4, config, constants, exceptions, types


LOG = logging.getLogger(__name__)


def authenticate(
    user_name: str | None = None,
    user_email: str | None = None,
    user_password: str | None = None,
    jwt: str | None = None,
    delete: bool = False,
):
    """
    Prompt for authentication information and save it to the config file
    """

    # We still have to accept --user_name for the back compatibility
    profile_name = user_name

    all_user_items = config.list_all_users()
    if all_user_items:
        _list_all_profiles(all_user_items)
    else:
        _welcome()

    # Make sure profile name either validated or existed
    if profile_name is not None:
        profile_name = profile_name.strip()
    else:
        if not _prompt_enabled():
            raise exceptions.MapillaryBadParameterError(
                "Profile name is required, please specify one with --user_name"
            )
        profile_name = _prompt_choose_profile_name(
            list(all_user_items.keys()), must_exist=delete
        )

    assert profile_name is not None, "profile_name should be set"

    if delete:
        config.remove_config(profile_name)
        LOG.info('Profile "%s" deleted', profile_name)
    else:
        if profile_name in all_user_items:
            LOG.warning(
                'The profile "%s" already exists and will be overridden',
                profile_name,
            )
        else:
            LOG.info('Creating new profile: "%s"', profile_name)

        if jwt:
            user_items: types.UserItem = {"user_upload_token": jwt}
            user_items = _verify_user_auth(_validate_profile(user_items))
        else:
            user_items = _prompt_login(
                user_email=user_email, user_password=user_password
            )
            _validate_profile(user_items)

        # Update the config with the new user items
        config.update_config(profile_name, user_items)

        # TODO: print more user information
        if profile_name in all_user_items:
            LOG.info(
                'Profile "%s" updated: %s', profile_name, api_v4._sanitize(user_items)
            )
        else:
            LOG.info(
                'Profile "%s" created: %s', profile_name, api_v4._sanitize(user_items)
            )


def fetch_user_items(
    user_name: str | None = None,
    organization_key: str | None = None,
) -> types.UserItem:
    """
    Read user information from the config file,
    or prompt the user to authenticate if the specified profile does not exist
    """

    # we still have to accept --user_name for the back compatibility
    profile_name = user_name

    all_user_items = config.list_all_users()
    if not all_user_items:
        authenticate(user_name=profile_name)

    # Fetch user information only here
    all_user_items = config.list_all_users()
    assert len(all_user_items) >= 1, "should have at least 1 profile"
    if profile_name is None:
        if len(all_user_items) > 1:
            if not _prompt_enabled():
                raise exceptions.MapillaryBadParameterError(
                    "Multiple user profiles found, please choose one with --user_name"
                )
            _list_all_profiles(all_user_items)
            profile_name = _prompt_choose_profile_name(
                list(all_user_items.keys()), must_exist=True
            )
            user_items = all_user_items[profile_name]
        else:
            profile_name, user_items = list(all_user_items.items())[0]
    else:
        if profile_name in all_user_items:
            user_items = all_user_items[profile_name]
        else:
            _list_all_profiles(all_user_items)
            raise exceptions.MapillaryBadParameterError(
                f'Profile "{profile_name}" not found'
            )

    assert profile_name is not None, "profile_name should be set"

    user_items = _verify_user_auth(_validate_profile(user_items))

    LOG.info(
        'Uploading to profile "%s": %s', profile_name, api_v4._sanitize(user_items)
    )

    if organization_key is not None:
        resp = api_v4.fetch_organization(
            user_items["user_upload_token"], organization_key
        )
        LOG.info("Uploading to Mapillary organization: %s", json.dumps(resp.json()))
        user_items["MAPOrganizationKey"] = organization_key

    return user_items


def _echo(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def _prompt(message: str) -> str:
    """Display prompt on stderr and get input from stdin"""
    print(message, end="", file=sys.stderr, flush=True)
    return input()


def _validate_profile(user_items: types.UserItem) -> types.UserItem:
    try:
        jsonschema.validate(user_items, types.UserItemSchema)
    except jsonschema.ValidationError as ex:
        raise exceptions.MapillaryBadParameterError(
            f"Invalid profile format: {ex.message}"
        )
    return user_items


def _verify_user_auth(user_items: types.UserItem) -> types.UserItem:
    """
    Verify that the user access token is valid
    """
    if constants._AUTH_VERIFICATION_DISABLED:
        return user_items

    try:
        resp = api_v4.fetch_user_or_me(
            user_access_token=user_items["user_upload_token"]
        )
    except requests.HTTPError as ex:
        if api_v4.is_auth_error(ex.response):
            message = api_v4.extract_auth_error_message(ex.response)
            raise exceptions.MapillaryUploadUnauthorizedError(message)
        else:
            raise ex

    user_json = resp.json()

    return {
        **user_items,
        "MAPSettingsUsername": user_json.get("username"),
        "MAPSettingsUserKey": user_json.get("id"),
    }


def _validate_profile_name(profile_name: str):
    if not (2 <= len(profile_name) <= 32):
        raise exceptions.MapillaryBadParameterError(
            "Profile name must be between 2 and 32 characters long"
        )

    pattern = re.compile(r"^[a-zA-Z]+[a-zA-Z0-9_-]*$")
    if not bool(pattern.match(profile_name)):
        raise exceptions.MapillaryBadParameterError(
            "Invalid profile name. Use only letters, numbers, hyphens and underscores"
        )


def _list_all_profiles(profiles: dict[str, types.UserItem]) -> None:
    _echo("Existing Mapillary profiles:")

    # Header
    _echo(f"{'':>5}  {'Profile name':<32} {'User ID':>16} {'Username':>32}")

    # List all profiles
    for idx, name in enumerate(profiles, 1):
        items = profiles[name]
        user_id = items.get("MAPSettingsUserKey", "N/A")
        username = items.get("MAPSettingsUsername", "N/A")
        _echo(f"{idx:>5}. {name:<32} {user_id:>16} {username:>32}")


def _is_interactive():
    # Check if stdout is connected to a terminal
    stdout_interactive = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False

    # Optionally, also check stdin and stderr
    stdin_interactive = sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False
    stderr_interactive = sys.stderr.isatty() if hasattr(sys.stderr, "isatty") else False

    # Return True if any stream is interactive
    return stdout_interactive or stdin_interactive or stderr_interactive


def _prompt_enabled() -> bool:
    if constants.PROMPT_DISABLED:
        return False

    if not _is_interactive():
        return False

    return True


def _is_login_retryable(ex: requests.HTTPError) -> bool:
    if 400 <= ex.response.status_code < 500:
        r = ex.response.json()
        subcode = r.get("error", {}).get("error_subcode")
        if subcode in [1348028, 1348092, 3404005, 1348131]:
            title = r.get("error", {}).get("error_user_title")
            message = r.get("error", {}).get("error_user_msg")
            LOG.error("%s: %s", title, message)
            return True
    return False


def _prompt_login(
    user_email: str | None = None,
    user_password: str | None = None,
) -> types.UserItem:
    _enabled = _prompt_enabled()

    if user_email is None:
        if not _enabled:
            raise exceptions.MapillaryBadParameterError("user_email is required")
        while not user_email:
            user_email = _prompt("Enter Mapillary user email: ").strip()
    else:
        user_email = user_email.strip()

    if user_password is None:
        if not _enabled:
            raise exceptions.MapillaryBadParameterError("user_password is required")
        while True:
            user_password = getpass.getpass("Enter Mapillary user password: ")
            if user_password:
                break

    try:
        resp = api_v4.get_upload_token(user_email, user_password)
    except requests.HTTPError as ex:
        if not _enabled:
            raise ex

        if _is_login_retryable(ex):
            return _prompt_login()

        raise ex

    data = resp.json()

    user_items: types.UserItem = {
        "user_upload_token": str(data["access_token"]),
        "MAPSettingsUserKey": str(data["user_id"]),
    }

    return user_items


def _prompt_choose_profile_name(
    existing_profile_names: T.Sequence[str], must_exist: bool = False
) -> str:
    assert _prompt_enabled(), "should not get here if prompting is disabled"

    existed = set(existing_profile_names)

    while True:
        if must_exist:
            prompt = "Enter an existing profile: "
        else:
            prompt = "Enter an existing profile or create a new one: "

        profile_name = _prompt(prompt).strip()

        if not profile_name:
            continue

        # Exit if it's found
        if profile_name in existed:
            break

        # Try to find by index
        try:
            profile_name = existing_profile_names[int(profile_name) - 1]
        except (ValueError, IndexError):
            pass
        else:
            # Exit if it's found
            break

        assert profile_name not in existed, (
            f"Profile {profile_name} must not exist here"
        )

        if must_exist:
            LOG.error('Profile "%s" not found', profile_name)
        else:
            try:
                _validate_profile_name(profile_name)
            except exceptions.MapillaryBadParameterError as ex:
                LOG.error("Error validating profile name: %s", ex)
                profile_name = ""
            else:
                break

    if must_exist:
        assert profile_name in existed, f"Profile {profile_name} must exist"

    return profile_name


def _welcome():
    _echo(
        """
================================================================================
                             Welcome to Mapillary!
================================================================================
  If you haven't registered yet, please visit https://www.mapillary.com/signup
  to create your account first.

  Once registered, proceed here to sign in.
================================================================================
    """
    )
