import os
import requests

from .error import print_error

API_ENDPOINT = os.getenv("API_PROXY_HOST", "https://a.mapillary.com")
MAPILLARY_WEB_CLIENT_ID = os.getenv(
    "MAPILLARY_WEB_CLIENT_ID", "MkJKbDA0bnZuZlcxeTJHTmFqN3g1dzo1YTM0NjRkM2EyZGU5MzBh"
)


def get_user(jwt):
    headers = {"Authorization": f"Bearer {jwt}"}
    resp = requests.get(
        f"{API_ENDPOINT}/v3/me",
        params={"client_id": MAPILLARY_WEB_CLIENT_ID},
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_user_organizations(user_key, auth_token):
    headers = {"Authorization": f"Bearer {auth_token}"}
    resp = requests.get(
        f"{API_ENDPOINT}/v3/users/{user_key}/organizations",
        params={"client_id": MAPILLARY_WEB_CLIENT_ID},
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()


def get_upload_token(mail, pwd):
    payload = {"email": mail, "password": pwd}
    resp = requests.post(
        f"{API_ENDPOINT}/v2/ua/login",
        params={"client_id": MAPILLARY_WEB_CLIENT_ID},
        json=payload,
    )
    if resp.status_code == 401:
        return None
    resp.raise_for_status()
    return resp.json().get("token")


def get_user_key(user_name):
    resp = requests.get(
        f"{API_ENDPOINT}/v3/users",
        params={"client_id": MAPILLARY_WEB_CLIENT_ID, "usernames": user_name},
    )
    resp.raise_for_status()
    resp = resp.json()
    if not resp or "key" not in resp[0]:
        print_error(f"Error, user name {user_name} does not exist...")
        return None
    return resp[0]["key"]
