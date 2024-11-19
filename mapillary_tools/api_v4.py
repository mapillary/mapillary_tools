import os
import typing as T

import requests

MAPILLARY_CLIENT_TOKEN = os.getenv(
    "MAPILLARY_CLIENT_TOKEN", "MLY|5675152195860640|6b02c72e6e3c801e5603ab0495623282"
)
MAPILLARY_GRAPH_API_ENDPOINT = os.getenv(
    "MAPILLARY_GRAPH_API_ENDPOINT", "https://graph.mapillary.com"
)
# https://requests.readthedocs.io/en/latest/user/advanced/#ssl-cert-verification
MAPILLARY__DISABLE_VERIFYING_SSL = (
    os.getenv("MAPILLARY__DISABLE_VERIFYING_SSL") == "TRUE"
)
REQUESTS_TIMEOUT = 60  # 1 minutes


def get_upload_token(email: str, password: str) -> requests.Response:
    resp = requests.post(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/login",
        params={"access_token": MAPILLARY_CLIENT_TOKEN},
        json={"email": email, "password": password, "locale": "en_US"},
        timeout=REQUESTS_TIMEOUT,
        verify=not MAPILLARY__DISABLE_VERIFYING_SSL,
    )
    resp.raise_for_status()
    return resp


def fetch_organization(
    user_access_token: str, organization_id: T.Union[int, str]
) -> requests.Response:
    resp = requests.get(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/{organization_id}",
        params={
            "fields": ",".join(["slug", "description", "name"]),
        },
        headers={
            "Authorization": f"OAuth {user_access_token}",
        },
        timeout=REQUESTS_TIMEOUT,
        verify=not MAPILLARY__DISABLE_VERIFYING_SSL,
    )
    resp.raise_for_status()
    return resp


ActionType = T.Literal[
    "upload_started_upload", "upload_finished_upload", "upload_failed_upload"
]


def logging(action_type: ActionType, properties: T.Dict) -> requests.Response:
    resp = requests.post(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/logging",
        json={
            "action_type": action_type,
            "properties": properties,
        },
        headers={
            "Authorization": f"OAuth {MAPILLARY_CLIENT_TOKEN}",
        },
        timeout=REQUESTS_TIMEOUT,
        verify=not MAPILLARY__DISABLE_VERIFYING_SSL,
    )
    resp.raise_for_status()
    return resp
