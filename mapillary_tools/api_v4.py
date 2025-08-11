from __future__ import annotations

import enum
import logging
import os
import typing as T

import requests

from . import http

LOG = logging.getLogger(__name__)
MAPILLARY_CLIENT_TOKEN = os.getenv(
    "MAPILLARY_CLIENT_TOKEN", "MLY|5675152195860640|6b02c72e6e3c801e5603ab0495623282"
)
MAPILLARY_GRAPH_API_ENDPOINT = os.getenv(
    "MAPILLARY_GRAPH_API_ENDPOINT", "https://graph.mapillary.com"
)
REQUESTS_TIMEOUT: float = 60  # 1 minutes


class HTTPContentError(Exception):
    """
    Raised when the HTTP response is ok (200) but the content is not as expected
    e.g. not JSON or not a valid response.
    """

    def __init__(self, message: str, response: requests.Response):
        self.response = response
        super().__init__(message)


class ClusterFileType(enum.Enum):
    ZIP = "zip"
    BLACKVUE = "mly_blackvue_video"
    CAMM = "mly_camm_video"
    MLY_BUNDLE_MANIFEST = "mly_bundle_manifest"


def create_user_session(user_access_token: str) -> requests.Session:
    session = http.Session()
    session.headers["Authorization"] = f"OAuth {user_access_token}"
    return session


def create_client_session(disable_logging: bool = False) -> requests.Session:
    session = http.Session()
    session.headers["Authorization"] = f"OAuth {MAPILLARY_CLIENT_TOKEN}"
    if disable_logging:
        session.disable_logging_request = True
        session.disable_logging_response = True
    return session


def is_auth_error(resp: requests.Response) -> bool:
    if resp.status_code in [401, 403]:
        return True

    if resp.status_code in [400]:
        try:
            error_body = resp.json()
        except Exception:
            error_body = {}

        type = error_body.get("debug_info", {}).get("type")
        if type in ["NotAuthorizedError"]:
            return True

    return False


def extract_auth_error_message(resp: requests.Response) -> str:
    assert is_auth_error(resp), "has to be an auth error"

    try:
        error_body = resp.json()
    except Exception:
        error_body = {}

    # from Graph APIs
    message = error_body.get("error", {}).get("message")
    if message is not None:
        return str(message)

    # from upload service
    message = error_body.get("debug_info", {}).get("message")
    if message is not None:
        return str(message)

    return resp.text


def get_upload_token(
    client_session: requests.Session, email: str, password: str
) -> requests.Response:
    url = f"{MAPILLARY_GRAPH_API_ENDPOINT}/login"
    json_data = {"email": email, "password": password, "locale": "en_US"}

    resp = client_session.post(url, json=json_data, timeout=REQUESTS_TIMEOUT)
    resp.raise_for_status()

    return resp


def fetch_organization(
    user_session: requests.Session, organization_id: int | str
) -> requests.Response:
    url = f"{MAPILLARY_GRAPH_API_ENDPOINT}/{organization_id}"
    params = {"fields": ",".join(["slug", "description", "name"])}

    resp = user_session.get(url, params=params, timeout=REQUESTS_TIMEOUT)
    resp.raise_for_status()

    return resp


def fetch_user_or_me(
    user_session: requests.Session, user_id: int | str | None = None
) -> requests.Response:
    if user_id is None:
        url = f"{MAPILLARY_GRAPH_API_ENDPOINT}/me"
    else:
        url = f"{MAPILLARY_GRAPH_API_ENDPOINT}/{user_id}"
    params = {"fields": ",".join(["id", "username"])}

    resp = user_session.get(url, params=params, timeout=REQUESTS_TIMEOUT)
    resp.raise_for_status()

    return resp


ActionType = T.Literal[
    "upload_started_upload", "upload_finished_upload", "upload_failed_upload"
]


def log_event(
    client_session: requests.Session, action_type: ActionType, properties: dict
) -> requests.Response:
    url = f"{MAPILLARY_GRAPH_API_ENDPOINT}/logging"
    json_data = {"action_type": action_type, "properties": properties}

    resp = client_session.post(url, json=json_data, timeout=REQUESTS_TIMEOUT)
    resp.raise_for_status()

    return resp


def finish_upload(
    user_session: requests.Session,
    file_handle: str,
    cluster_filetype: ClusterFileType,
    organization_id: int | str | None = None,
) -> requests.Response:
    url = f"{MAPILLARY_GRAPH_API_ENDPOINT}/finish_upload"
    json_data: dict[str, str | int] = {
        "file_handle": file_handle,
        "file_type": cluster_filetype.value,
    }
    if organization_id is not None:
        json_data["organization_id"] = organization_id

    resp = user_session.post(url, json=json_data, timeout=REQUESTS_TIMEOUT)
    resp.raise_for_status()

    return resp


def jsonify_response(resp: requests.Response) -> T.Any:
    """
    Convert the response to JSON, raising HTTPContentError if the response is not JSON.
    """
    try:
        return resp.json()
    except requests.JSONDecodeError as ex:
        raise HTTPContentError("Invalid JSON response", resp) from ex
