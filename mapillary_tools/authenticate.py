# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import getpass
import logging
import re
import sys
import typing as T

import jsonschema
import requests

from . import api_v4, config, constants, exceptions, http


LOG = logging.getLogger(__name__)
# Profile names and organization names
_NAME_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]*")
_ORGANIZATION_ID_PATTERN = re.compile(r"[0-9]+")


def authenticate(
    user_name: str | None = None,
    user_email: str | None = None,
    user_password: str | None = None,
    jwt: str | None = None,
    delete: bool = False,
    organization_name: str | None = None,
):
    """
    Prompt for authentication information and save it to the config file
    """

    if organization_name is not None and not delete:
        raise exceptions.MapillaryBadParameterError(
            "authenticate takes --organization_name only with --delete. To save an "
            "organization name, upload with --organization_key ID --organization_name NAME"
        )

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

    if delete and organization_name is not None:
        _delete_organization(profile_name, organization_name.strip(), all_user_items)
    elif delete:
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
            user_items: config.UserItem = {"user_upload_token": jwt}
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
                'Profile "%s" updated: %s', profile_name, http._sanitize(user_items)
            )
        else:
            LOG.info(
                'Profile "%s" created: %s', profile_name, http._sanitize(user_items)
            )


def fetch_user_items(
    user_name: str | None = None,
    organization_key: str | None = None,
    organization_name: str | None = None,
) -> config.UserItem:
    """
    Read user information from the config file,
    or prompt the user to authenticate if the specified profile does not exist.

    Upload to the organization ID organization_key, and save it in the profile
    under organization_name if both are given. With organization_name alone,
    upload to the organization ID saved under it
    """

    # we still have to accept --user_name for the back compatibility
    profile_name = user_name

    if organization_name is not None:
        organization_name = organization_name.strip()
        _validate_organization_name(organization_name)

    if organization_key is not None:
        organization_key = organization_key.strip()
        if not _ORGANIZATION_ID_PATTERN.fullmatch(organization_key):
            all_user_items = config.list_all_users()
            if profile_name in all_user_items:
                _list_organizations(
                    profile_name,
                    config.list_organizations(all_user_items[profile_name]),
                )
            elif all_user_items:
                _list_all_profiles(all_user_items)
            raise exceptions.MapillaryBadParameterError(
                "--organization_key takes an organization ID; "
                "for a saved name use --organization_name NAME"
            )

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

    saved_organizations = config.list_organizations(user_items)
    organization_id = organization_key
    if organization_name is not None and organization_key is None:
        organization_id = saved_organizations.get(organization_name)
        if organization_id is None:
            _list_organizations(profile_name, saved_organizations)
            raise exceptions.MapillaryBadParameterError(
                f'Organization "{organization_name}" not found in profile "{profile_name}". '
                f"To save it, give its ID with --organization_key ID --organization_name {organization_name}"
            )

    try:
        LOG.info(f'Verifying profile "{profile_name}"...')
        user_items = _verify_user_auth(_validate_profile(user_items))

        LOG.info(
            f'Uploading to profile "{profile_name}": {user_items.get("MAPSettingsUsername")} (ID: {user_items.get("MAPSettingsUserKey")})'
        )

        if organization_id is not None:
            with api_v4.create_user_session(user_items["user_upload_token"]) as session:
                resp = api_v4.fetch_organization(session, organization_id)
            data = api_v4.jsonify_response(resp)
            LOG.info(
                f"Uploading to organization: {data.get('name')} (ID: {data.get('id')})"
            )
            user_items["MAPOrganizationKey"] = data.get("id")

            if organization_key is not None:
                # The ID as the server returns it, which the upload goes to
                organization_id = str(data.get("id") or organization_key)
                if organization_name is not None:
                    _save_organization(
                        profile_name,
                        organization_name,
                        organization_id,
                        data.get("name"),
                        saved_organizations,
                    )
                else:
                    _hint_organization_name(
                        profile_name, organization_id, saved_organizations
                    )

    except requests.Timeout as ex:
        raise exceptions.MapillaryUploadTimeoutError(str(ex)) from ex

    except requests.ConnectionError as ex:
        raise exceptions.MapillaryUploadConnectionError(str(ex)) from ex

    return user_items


def _save_organization(
    profile_name: str,
    organization_name: str,
    organization_id: str,
    organization_title: str | None,
    saved_organizations: dict[str, str],
) -> None:
    saved_id = saved_organizations.get(organization_name)
    if saved_id != organization_id:
        if saved_id is not None:
            LOG.warning(
                'The organization "%s" (ID: %s) already exists in profile "%s" and will be overridden',
                organization_name,
                saved_id,
                profile_name,
            )
        config.save_organization(profile_name, organization_name, organization_id)
    LOG.info(
        'Saved organization "%s": %s (ID: %s) in profile "%s"',
        organization_name,
        organization_title,
        organization_id,
        profile_name,
    )


def _hint_organization_name(
    profile_name: str, organization_id: str, saved_organizations: dict[str, str]
) -> None:
    saved_names = [
        name
        for name, saved_id in saved_organizations.items()
        if saved_id == organization_id
    ]
    if saved_names:
        LOG.info(
            'This organization is saved in profile "%s" as "%s": next time you can use --organization_name %s',
            profile_name,
            saved_names[0],
            saved_names[0],
        )
    else:
        LOG.info(
            "To upload to this organization by a name next time, add --organization_name NAME"
        )


def _delete_organization(
    profile_name: str,
    organization_name: str,
    all_user_items: dict[str, config.UserItem],
) -> None:
    if profile_name not in all_user_items:
        raise exceptions.MapillaryBadParameterError(
            f'Profile "{profile_name}" not found'
        )
    saved_id = config.list_organizations(all_user_items[profile_name]).get(
        organization_name
    )
    if saved_id is None or not config.remove_organization(
        profile_name, organization_name
    ):
        raise exceptions.MapillaryBadParameterError(
            f'Organization "{organization_name}" not found in profile "{profile_name}"'
        )
    LOG.info(
        'Deleted organization "%s" (ID: %s) from profile "%s"',
        organization_name,
        saved_id,
        profile_name,
    )


def _echo(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def _prompt(message: str) -> str:
    """Display prompt on stderr and get input from stdin"""
    print(message, end="", file=sys.stderr, flush=True)
    return input()


def _validate_profile(user_items: config.UserItem) -> config.UserItem:
    try:
        config.UserItemSchemaValidator.validate(user_items)
    except jsonschema.ValidationError as ex:
        raise exceptions.MapillaryBadParameterError(
            f"Invalid profile format: {ex.message}"
        )
    return user_items


def _verify_user_auth(user_items: config.UserItem) -> config.UserItem:
    """
    Verify that the user access token is valid
    """
    if constants._AUTH_VERIFICATION_DISABLED:
        return user_items

    with api_v4.create_user_session(user_items["user_upload_token"]) as session:
        try:
            resp = api_v4.fetch_user_or_me(session)
        except requests.HTTPError as ex:
            if api_v4.is_auth_error(ex.response):
                message = api_v4.extract_auth_error_message(ex.response)
                raise exceptions.MapillaryUploadUnauthorizedError(message)
            else:
                raise ex

    data = api_v4.jsonify_response(resp)

    return {
        **user_items,
        "MAPSettingsUsername": data.get("username"),
        "MAPSettingsUserKey": data.get("id"),
    }


def _validate_name(name: str, kind: str) -> None:
    if not (2 <= len(name) <= 32):
        raise exceptions.MapillaryBadParameterError(
            f"{kind.capitalize()} must be between 2 and 32 characters long"
        )

    if not _NAME_PATTERN.fullmatch(name):
        raise exceptions.MapillaryBadParameterError(
            f'Invalid {kind} "{name}". Use only letters, numbers, hyphens and underscores, starting with a letter'
        )


def _validate_profile_name(profile_name: str):
    _validate_name(profile_name, "profile name")


def _validate_organization_name(organization_name: str):
    # The same rules as profile names, so that a name is never taken for an ID
    _validate_name(organization_name, "organization name")


def _list_all_profiles(profiles: dict[str, config.UserItem]) -> None:
    _echo("Existing Mapillary profiles:")

    # Header
    _echo(f"{'':>5}  {'Profile name':<32} {'User ID':>16} {'Username':>32}")

    # List all profiles
    for idx, name in enumerate(profiles, 1):
        items = profiles[name]
        user_id = items.get("MAPSettingsUserKey", "N/A")
        username = items.get("MAPSettingsUsername", "N/A")
        _echo(f"{idx:>5}. {name:<32} {user_id:>16} {username:>32}")
        for organization_name, organization_id in config.list_organizations(
            items
        ).items():
            _echo(
                f"{'':>7}  {'organization ' + organization_name:<30} {organization_id:>16}"
            )


def _list_organizations(profile_name: str, organizations: dict[str, str]) -> None:
    if not organizations:
        _echo(f'No organizations saved in profile "{profile_name}"')
        return

    _echo(f'Saved organizations in profile "{profile_name}":')

    # Header
    _echo(f"{'':>5}  {'Organization name':<32} {'Organization ID':>16}")

    for idx, (name, organization_id) in enumerate(organizations.items(), 1):
        _echo(f"{idx:>5}. {name:<32} {organization_id:>16}")


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
) -> config.UserItem:
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

    with api_v4.create_client_session() as session:
        try:
            resp = api_v4.get_upload_token(session, user_email, user_password)
        except requests.HTTPError as ex:
            if not _enabled:
                raise ex

            if _is_login_retryable(ex):
                return _prompt_login()

            raise ex

    data = api_v4.jsonify_response(resp)

    user_items: config.UserItem = {
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
