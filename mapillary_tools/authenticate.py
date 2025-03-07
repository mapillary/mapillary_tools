import getpass
import json
import logging
import sys
import typing as T

import jsonschema
import requests

from . import api_v4, config, types


LOG = logging.getLogger(__name__)


def authenticate(
    user_name: T.Optional[str] = None,
    user_email: T.Optional[str] = None,
    user_password: T.Optional[str] = None,
    jwt: T.Optional[str] = None,
):
    # we still accept --user_name for the back compatibility
    profile_name = user_name

    if profile_name:
        profile_name = profile_name.strip()

    while not profile_name:
        profile_name = input(
            "Enter the Mapillary username you would like to (re)authenticate: "
        )
        profile_name = profile_name.strip()

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
        profile_name, user_items = prompt_user_for_user_items(profile_name)

    config.update_config(profile_name, user_items)


def prompt_user_for_user_items(
    profile_name: str | None,
) -> T.Tuple[str, types.UserItem]:
    print(
        """
================================================================================
                            Welcome to Mapillary!
================================================================================
If you haven't registered yet, please visit the following link to sign up first:
https://www.mapillary.com/signup
After the registration, proceed here to sign in.
================================================================================
""".strip(),
        file=sys.stderr,
    )

    if profile_name is None:
        profile_name = input("Enter the profile name you would like to create: ")

    print(f"Sign in for user {profile_name}", file=sys.stderr)
    user_email = input("Enter your Mapillary user email: ")
    user_password = getpass.getpass("Enter Mapillary user password: ")

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


def authenticate_user(profile_name: str | None) -> types.UserItem:
    if profile_name is not None:
        user_items = config.load_user(profile_name)
        if user_items is not None:
            try:
                jsonschema.validate(user_items, types.UserItemSchema)
            except jsonschema.ValidationError:
                pass
            else:
                return user_items

    profile_name, user_items = prompt_user_for_user_items(profile_name)
    jsonschema.validate(user_items, types.UserItemSchema)
    config.update_config(profile_name, user_items)

    return user_items


def prompt_choose_user_profile(
    all_user_items: T.Dict[str, types.UserItem],
) -> types.UserItem:
    print("Found multiple Mapillary profiles:", file=sys.stderr)
    profiles = list(all_user_items.keys())

    for i, name in enumerate(profiles, 1):
        print(f"{i:5}. {name}", file=sys.stderr)

    while True:
        try:
            choice = int(
                input("Which user profile would you like to use? Enter the number: ")
            )
        except ValueError:
            print("Invalid input. Please enter a number.", file=sys.stderr)
        else:
            if 1 <= choice <= len(all_user_items):
                user_items = all_user_items[profiles[choice - 1]]
                break

            print(
                f"Please enter a number between 1 and {len(profiles)}.", file=sys.stderr
            )

    return user_items


def fetch_user_items(
    profile_name: T.Optional[str] = None, organization_key: T.Optional[str] = None
) -> types.UserItem:
    if profile_name is None:
        all_user_items = config.list_all_users()
        if not all_user_items:
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
