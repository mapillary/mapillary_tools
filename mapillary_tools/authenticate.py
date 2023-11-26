import getpass
import logging
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
    if user_name:
        user_name = user_name.strip()

    while not user_name:
        user_name = input(
            "Enter the Mapillary username you would like to (re)authenticate: "
        )
        user_name = user_name.strip()

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
        user_items = prompt_user_for_user_items(user_name)

    config.update_config(user_name, user_items)


def prompt_user_for_user_items(user_name: str) -> types.UserItem:
    print(f"Sign in for user {user_name}")
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
                return prompt_user_for_user_items(user_name)
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

    return {
        "MAPSettingsUserKey": user_key,
        "user_upload_token": upload_token,
    }


def authenticate_user(user_name: str) -> types.UserItem:
    user_items = config.load_user(user_name)
    if user_items is not None:
        try:
            jsonschema.validate(user_items, types.UserItemSchema)
        except jsonschema.ValidationError:
            pass
        else:
            return user_items

    user_items = prompt_user_for_user_items(user_name)
    jsonschema.validate(user_items, types.UserItemSchema)
    config.update_config(user_name, user_items)

    return user_items
