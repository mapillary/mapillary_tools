import getpass
import json
import logging
import sys
import typing as T

import jsonschema
import requests

from . import api_v4, config, types


LOG = logging.getLogger(__name__)


def echo(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def prompt(message: str) -> str:
    """Display prompt on stderr and get input from stdin"""
    print(message, end="", file=sys.stderr, flush=True)
    return input()


def authenticate(
    user_name: T.Optional[str] = None,
    user_email: T.Optional[str] = None,
    user_password: T.Optional[str] = None,
    jwt: T.Optional[str] = None,
):
    # we still have to accept --user_name for the back compatibility
    profile_name = user_name

    all_user_items = config.list_all_users()
    if all_user_items:
        echo("Existing Mapillary profiles:")
        _list_all_profiles(all_user_items)
    else:
        welcome()

    if profile_name:
        profile_name = profile_name.strip()

    while not profile_name:
        profile_name = prompt(
            "Enter the Mapillary profile you would like to (re)authenticate: "
        ).strip()

    if profile_name in all_user_items:
        LOG.warning(
            'The profile "%s" already exists and will be overridden.',
            profile_name,
        )

    if jwt:
        user_items: types.UserItem = {
            "user_upload_token": jwt,
        }
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
        profile_name, user_items = prompt_user_for_user_items(profile_name)

    LOG.info('Authenticated as "%s"', profile_name)
    config.update_config(profile_name, user_items)


def _list_all_profiles(profiles: T.Dict[str, types.UserItem]) -> None:
    for idx, name in enumerate(profiles, 1):
        echo(f"{idx:>5}. {name:<32} {profiles[name].get('MAPSettingsUserKey')}")


def prompt_user_for_user_items(
    profile_name: T.Optional[str],
) -> T.Tuple[str, types.UserItem]:
    if profile_name is None:
        while not profile_name:
            profile_name = prompt(
                "Enter the profile name you would like to authenticate: "
            ).strip()

    user_email = ""
    while not user_email:
        user_email = prompt(
            f'Enter Mapillary user email for "{profile_name}": '
        ).strip()

    user_password = getpass.getpass(
        f'Enter Mapillary user password for "{profile_name}": '
    )

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
                return prompt_user_for_user_items(profile_name)
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


def authenticate_user(profile_name: T.Optional[str]) -> types.UserItem:
    if profile_name is not None:
        user_items = config.load_user(profile_name)
        if user_items is None:
            LOG.info('Profile "%s" not found in config', profile_name)
        else:
            try:
                jsonschema.validate(user_items, types.UserItemSchema)
            except jsonschema.ValidationError:
                # If the user_items in config are invalid, proceed with the user input
                LOG.warning("Invalid user items for profile: %s", profile_name)
            else:
                return user_items

    profile_name, user_items = prompt_user_for_user_items(profile_name)
    jsonschema.validate(user_items, types.UserItemSchema)

    # Update the config with the new user items
    LOG.info('Authenticated as "%s"', profile_name)
    config.update_config(profile_name, user_items)

    return user_items


def prompt_choose_user_profile(
    all_user_items: T.Dict[str, types.UserItem],
) -> types.UserItem:
    echo("Found multiple Mapillary profiles:")
    profiles = list(all_user_items.keys())

    _list_all_profiles(all_user_items)

    while True:
        c = prompt(
            "Which user profile would you like to use? Enter the number: "
        ).strip()

        try:
            choice = int(c)
        except ValueError:
            echo("Invalid input. Please enter a number.")
        else:
            if 1 <= choice <= len(all_user_items):
                user_items = all_user_items[profiles[choice - 1]]
                break

            echo(f"Please enter a number between 1 and {len(profiles)}.")

    return user_items


def welcome():
    echo(
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


def fetch_user_items(
    user_name: T.Optional[str] = None, organization_key: T.Optional[str] = None
) -> types.UserItem:
    # we still have to accept --user_name for the back compatibility
    profile_name = user_name

    if profile_name is None:
        all_user_items = config.list_all_users()
        if not all_user_items:
            welcome()
            user_items = authenticate_user(None)
            # raise exceptions.MapillaryBadParameterError(
            #     "No Mapillary profile found. Add one with --user_name"
            # )
        elif len(all_user_items) == 1:
            user_items = list(all_user_items.values())[0]
        else:
            user_items = prompt_choose_user_profile(all_user_items)
    else:
        user_items = authenticate_user(profile_name)

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
