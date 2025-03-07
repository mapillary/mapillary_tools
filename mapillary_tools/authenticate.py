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
    user_name: T.Optional[str] = None,
    user_email: T.Optional[str] = None,
    user_password: T.Optional[str] = None,
    jwt: T.Optional[str] = None,
):
    # we still have to accept --user_name for the back compatibility
    profile_name = user_name

    if profile_name:
        profile_name = profile_name.strip()

    all_user_items = config.list_all_users()
    if all_user_items:
        _list_all_profiles(all_user_items)
    else:
        _welcome()

    if not profile_name:
        profile_name = _prompt_profile_name(skip_validation=True)

    if profile_name in all_user_items:
        LOG.warning(
            'The profile "%s" already exists and will be overridden',
            profile_name,
        )
    else:
        # validate only new profile names
        _validate_profile_name(profile_name)

    if jwt:
        user_items: types.UserItem = {"user_upload_token": jwt}
    elif user_email and user_password:
        resp = api_v4.get_upload_token(user_email, user_password)
        data = resp.json()
        user_items = {
            "MAPSettingsUserKey": data["user_id"],
            "user_upload_token": data["access_token"],
        }
    else:
        if user_email or user_password:
            LOG.warning(
                "Both user_email and user_password must be provided to authenticate"
            )

        if not _prompt_enabled():
            raise exceptions.MapillaryBadParameterError(
                "Authentication required, but prompting is disabled"
            )

        profile_name, user_items = _prompt_user_for_user_items(profile_name)

    LOG.info('Authenticated as "%s"', profile_name)
    config.update_config(profile_name, user_items)


def fetch_user_items(
    user_name: T.Optional[str] = None, organization_key: T.Optional[str] = None
) -> types.UserItem:
    # we still have to accept --user_name for the back compatibility
    profile_name = user_name

    all_user_items = config.list_all_users()
    if not all_user_items:
        _welcome()

    if profile_name is None:
        if len(all_user_items) == 0:
            user_items = _load_or_authenticate_user()
        elif len(all_user_items) == 1:
            user_items = list(all_user_items.values())[0]
        else:
            if not _prompt_enabled():
                raise exceptions.MapillaryBadParameterError(
                    "Multiple user profiles found, please choose one with --user_name"
                )
            user_items = _prompt_choose_user_profile(all_user_items)
    else:
        user_items = _load_or_authenticate_user(profile_name)

    if organization_key is not None:
        resp = api_v4.fetch_organization(
            user_items["user_upload_token"], organization_key
        )
        org = resp.json()
        LOG.info("Uploading to organization: %s", json.dumps(org))
        user_items = T.cast(
            types.UserItem, {**user_items, "MAPOrganizationKey": organization_key}
        )
    return user_items


def _echo(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def _prompt(message: str) -> str:
    """Display prompt on stderr and get input from stdin"""
    print(message, end="", file=sys.stderr, flush=True)
    return input()


def _prompt_profile_name(skip_validation: bool = False) -> str:
    assert _prompt_enabled(), "should not get here if prompting is disabled"

    profile_name = ""

    while not profile_name:
        profile_name = _prompt(
            "Enter the Mapillary profile you would like to (re)authenticate: "
        ).strip()

        if profile_name:
            if skip_validation:
                break

            try:
                _validate_profile_name(profile_name)
            except ValueError as ex:
                LOG.error("Error validating profile name: %s", ex)
                profile_name = ""
            else:
                break

    return profile_name


def _validate_profile_name(profile_name: str):
    if not (2 <= len(profile_name) <= 32):
        raise exceptions.MapillaryBadParameterError(
            "Profile name must be between 2 and 32 characters long"
        )

    pattern = re.compile(r"^[a-zA-Z0-9_-]+$")
    if not bool(pattern.match(profile_name)):
        raise exceptions.MapillaryBadParameterError(
            "Invalid profile name. Use only letters, numbers, hyphens and underscores"
        )


def _list_all_profiles(profiles: T.Dict[str, types.UserItem]) -> None:
    _echo("Existing Mapillary profiles:")
    for idx, name in enumerate(profiles, 1):
        _echo(f"{idx:>5}. {name:<32} {profiles[name].get('MAPSettingsUserKey')}")


def _is_interactive():
    """
    Determine if the current environment is interactive by checking
    if standard streams are connected to a TTY device.

    Returns:
        bool: True if running in an interactive terminal, False otherwise
    """
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


def _prompt_user_for_user_items(
    profile_name: T.Optional[str],
) -> T.Tuple[str, types.UserItem]:
    assert _prompt_enabled(), "should not get here if prompting is disabled"

    if profile_name is None:
        profile_name = _prompt_profile_name()

    LOG.info('Authenticating as "%s"', profile_name)

    user_email = ""
    while not user_email:
        user_email = _prompt("Enter Mapillary user email: ").strip()

    while True:
        user_password = getpass.getpass("Enter Mapillary user password: ")
        if user_password:
            break

    try:
        resp = api_v4.get_upload_token(user_email, user_password)
    except requests.HTTPError as ex:
        if (
            isinstance(ex, requests.HTTPError)
            and isinstance(ex.response, requests.Response)
            and 400 <= ex.response.status_code < 500
        ):
            r = ex.response.json()
            subcode = r.get("error", {}).get("error_subcode")
            if subcode in [1348028, 1348092, 3404005, 1348131]:
                title = r.get("error", {}).get("error_user_title")
                message = r.get("error", {}).get("error_user_msg")
                LOG.error("%s: %s", title, message)
                return _prompt_user_for_user_items(profile_name)
            else:
                raise ex
        else:
            raise ex

    data = resp.json()
    upload_token = T.cast(str, data.get("access_token"))
    user_key = T.cast(str, data.get("user_id"))
    if not isinstance(upload_token, str) or not isinstance(user_key, (str, int)):
        raise RuntimeError(
            f"Error extracting user_key or token from the login response: {data}"
        )

    if isinstance(user_key, int):
        user_key = str(user_key)

    return profile_name, {
        "MAPSettingsUserKey": user_key,
        "user_upload_token": upload_token,
    }


def _load_or_authenticate_user(profile_name: T.Optional[str] = None) -> types.UserItem:
    if profile_name is not None:
        user_items = config.load_user(profile_name)
        if user_items is None:
            LOG.info('Profile "%s" not found in config', profile_name)
            # validate here since we are going to create this profile
            _validate_profile_name(profile_name)
        else:
            try:
                jsonschema.validate(user_items, types.UserItemSchema)
            except jsonschema.ValidationError:
                # If the user_items in config are invalid, proceed with the user input
                LOG.warning("Invalid user items for profile: %s", profile_name)
            else:
                return user_items

    if not _prompt_enabled():
        raise exceptions.MapillaryBadParameterError(
            f'Profile "{profile_name}" not found (and prompting disabled)'
        )

    profile_name, user_items = _prompt_user_for_user_items(profile_name)
    jsonschema.validate(user_items, types.UserItemSchema)

    # Update the config with the new user items
    LOG.info('Authenticated as "%s"', profile_name)
    config.update_config(profile_name, user_items)

    return user_items


def _prompt_choose_user_profile(
    all_user_items: T.Dict[str, types.UserItem],
) -> types.UserItem:
    assert _prompt_enabled(), "should not get here if prompting is disabled"

    _list_all_profiles(all_user_items)
    while True:
        profile_name = _prompt_profile_name()
        if profile_name in all_user_items:
            break
        _echo(f'Profile "{profile_name}" not found')

    return all_user_items[profile_name]


def _welcome():
    _echo(
        """
================================================================================
                            Welcome to Mapillary!
================================================================================
If you haven't registered yet, please visit the following link to sign up first:
https://www.mapillary.com/signup
After the registration, proceed here to sign in.
================================================================================
    """.strip()
    )
