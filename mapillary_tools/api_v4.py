import os
import requests
from typing import Union

MAPILLARY_WEB_CLIENT_ID = os.getenv(
    "MAPILLARY_WEB_CLIENT_ID", "MLY|5675152195860640|6b02c72e6e3c801e5603ab0495623282"
)
MAPILLARY_GRAPH_API_ENDPOINT = os.getenv(
    "MAPILLARY_GRAPH_API_ENDPOINT", "https://graph.mapillary.com"
)


def get_upload_token(email: str, password: str) -> dict:
    resp = requests.post(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/login",
        params={"access_token": MAPILLARY_WEB_CLIENT_ID},
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.json()


def fetch_organization(
    user_access_token: str, organization_id: Union[int, str]
) -> requests.Response:
    resp = requests.get(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/{organization_id}",
        params={
            "fields": ",".join(["slug", "description", "name"]),
        },
        headers={
            "Authorization": f"OAuth {user_access_token}",
        },
    )
    return resp
