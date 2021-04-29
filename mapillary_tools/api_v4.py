import os
import requests
from typing import Optional

MAPILLARY_WEB_CLIENT_ID = os.getenv(
    "MAPILLARY_WEB_CLIENT_ID", "MkJKbDA0bnZuZlcxeTJHTmFqN3g1dzo1YTM0NjRkM2EyZGU5MzBh"
)
MAPILLARY_GRAPH_API_ENDPOINT = os.getenv(
    "MAPILLARY_GRAPH_API_ENDPOINT", "https://a.mapillary.com/v4"
)


def get_me(access_token: str):
    headers = {"Authorization": f"OAuth {access_token}"}
    resp = requests.get(f"{MAPILLARY_GRAPH_API_ENDPOINT}/me", headers=headers)
    resp.raise_for_status()
    return resp.json()


def get_upload_token(email: str, password: str) -> Optional[dict]:
    payload = {"email": email, "password": password}
    resp = requests.post(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/login",
        params={"access_token": MAPILLARY_WEB_CLIENT_ID},
        json=payload,
    )
    if resp.status_code == 401:
        return None
    resp.raise_for_status()
    return resp.json()
