import getpass
import json
import logging
import re
import sys
import typing as T

import requests

from . import api_v4, config, constants, exceptions, types


LOG = logging.getLogger(__name__)


def authenticate(
    user_name: T.Optional[str] = None,
    user_email: T.Optional[str] = None,
    user_password: T.Optional[str] = None,
    jwt: T.Optional[str] = None,
):
    """
    Prompt for authentication information and save it to the config file
    """

    # we still have to accept --user_name for the back compatibility
    profile_name = user_name

    all_user_items = config.list_all_users()
    if all_user_items:
        _list_all_profiles(all_user_items)
    else:
        _welcome()

    # Make sure profile name either validated or existed
    if profile_name:
        profile_name = profile_name.strip()
    else:
        if not _prompt_enabled():
            raise exceptions.MapillaryBadParameterError(
                "Profile name is required, please specify one with --user_name"
            )
        profile_name = _prompt_profile_name()

    assert profile_name is not None, "profile_name should be set"

    if profile_name in all_user_items:
        LOG.warning(
            'The profile "%s" already exists and will be overridden',
            profile_name,
        )
    else:
        # validate only new profile names
        _validate_profile_name(profile_name)
        LOG.info('Creating new profile: "%s"', profile_name)

    if jwt:
        user_items: types.UserItem = {"user_upload_token": jwt}
    else:
        user_items = _prompt_login(user_email=user_email, user_password=user_password)

    _test_auth_and_update_user(user_items)

    # Update the config with the new user items
    config.update_config(profile_name, user_items)

    # TODO: print more user information
    if profile_name in all_user_items:
        LOG.info('Profile "%s" updated', profile_name)
    else:
        LOG.info('Profile "%s" created', profile_name)


def fetch_user_items(
    user_name: T.Optional[str] = None,
    organization_key: T.Optional[str] = None,
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
            profile_name, user_items = _prompt_choose_user_profile(all_user_items)
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

    user_json = _test_auth_and_update_user(user_items)
    if user_json is not None:
        LOG.info("Uploading to Mapillary user: %s", json.dumps(user_json))

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


def _test_auth_and_update_user(
    user_items: types.UserItem,
) -> T.Optional[T.Dict[str, str]]:
    try:
        resp = api_v4.fetch_user_or_me(
            user_access_token=user_items["user_upload_token"]
        )
    except requests.HTTPError as ex:
        if api_v4.is_auth_error(ex.response):
            message = api_v4.extract_auth_error_message(ex.response)
            raise exceptions.MapillaryUploadUnauthorizedError(message)
        else:
            # The point of this function is to test if the auth works, so we don't throw any non-auth errors
            LOG.warning("Error testing the auth: %s", api_v4.readable_http_error(ex))
            return None

    user_json = resp.json()
    if user_json is not None:
        username = user_json.get("username")
        if username is not None:
            user_items["MAPSettingsUsername"] = username

        user_id = user_json.get("id")
        if user_id is not None:
            user_items["MAPSettingsUserKey"] = user_id

    return user_json


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


def _retryable_login(ex: requests.HTTPError) -> bool:
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
    user_email: T.Optional[str] = None,
    user_password: T.Optional[str] = None,
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

        if _retryable_login(ex):
            return _prompt_login()

        raise ex

    data = resp.json()

    user_items: types.UserItem = {
        "user_upload_token": str(data["access_token"]),
        "MAPSettingsUserKey": str(data["user_id"]),
    }

    return user_items


def _prompt_choose_user_profile(
    all_user_items: T.Dict[str, types.UserItem],
) -> T.Tuple[str, types.UserItem]:
    if not _prompt_enabled():
        raise exceptions.MapillaryBadParameterError(
            "Multiple user profiles found, please choose one with --user_name"
        )

    _list_all_profiles(all_user_items)
    while True:
        profile_name = _prompt_profile_name(skip_validation=True)
        if profile_name in all_user_items:
            break
        _echo(f'Profile "{profile_name}" not found')

    return profile_name, all_user_items[profile_name]


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
