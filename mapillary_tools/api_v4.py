from __future__ import annotations

import enum
import logging
import os
import ssl
import typing as T
from json import dumps

import requests
from requests.adapters import HTTPAdapter

LOG = logging.getLogger(__name__)
MAPILLARY_CLIENT_TOKEN = os.getenv(
    "MAPILLARY_CLIENT_TOKEN", "MLY|5675152195860640|6b02c72e6e3c801e5603ab0495623282"
)
MAPILLARY_GRAPH_API_ENDPOINT = os.getenv(
    "MAPILLARY_GRAPH_API_ENDPOINT", "https://graph.mapillary.com"
)
REQUESTS_TIMEOUT = 60  # 1 minutes
USE_SYSTEM_CERTS: bool = False


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


class HTTPSystemCertsAdapter(HTTPAdapter):
    """
    This adapter uses the system's certificate store instead of the certifi module.

    The implementation is based on the project https://pypi.org/project/pip-system-certs/,
    which has a system-wide effect.
    """

    def init_poolmanager(self, *args, **kwargs):
        ssl_context = ssl.create_default_context()
        ssl_context.load_default_certs()
        kwargs["ssl_context"] = ssl_context

        super().init_poolmanager(*args, **kwargs)

    def cert_verify(self, *args, **kwargs):
        super().cert_verify(*args, **kwargs)

        # By default Python requests uses the ca_certs from the certifi module
        # But we want to use the certificate store instead.
        # By clearing the ca_certs variable we force it to fall back on that behaviour (handled in urllib3)
        if "conn" in kwargs:
            conn = kwargs["conn"]
        else:
            conn = args[0]

        conn.ca_certs = None


@T.overload
def _truncate(s: bytes, limit: int = 256) -> bytes | str: ...


@T.overload
def _truncate(s: str, limit: int = 256) -> str: ...


def _truncate(s, limit=256):
    if limit < len(s):
        if isinstance(s, bytes):
            try:
                s = s.decode("utf-8")
            except UnicodeDecodeError:
                pass
        remaining = len(s) - limit
        if isinstance(s, bytes):
            return s[:limit] + f"...({remaining} bytes truncated)".encode("utf-8")
        else:
            return str(s[:limit]) + f"...({remaining} chars truncated)"
    else:
        return s


def _sanitize(headers: T.Mapping[T.Any, T.Any]) -> T.Mapping[T.Any, T.Any]:
    new_headers = {}

    for k, v in headers.items():
        if k.lower() in [
            "authorization",
            "cookie",
            "x-fb-access-token",
            "access-token",
            "access_token",
            "password",
            "user_upload_token",
        ]:
            new_headers[k] = "[REDACTED]"
        else:
            if isinstance(v, (str, bytes)):
                new_headers[k] = T.cast(T.Any, _truncate(v))
            else:
                new_headers[k] = v

    return new_headers


def _log_debug_request(
    method: str,
    url: str,
    json: dict | None = None,
    params: dict | None = None,
    headers: dict | None = None,
):
    if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
        return

    msg = f"HTTP {method} {url}"

    if USE_SYSTEM_CERTS:
        msg += " (w/sys_certs)"

    if json:
        t = _truncate(dumps(_sanitize(json)))
        msg += f" JSON={t}"

    if params:
        msg += f" PARAMS={_sanitize(params)}"

    if headers:
        msg += f" HEADERS={_sanitize(headers)}"

    msg = msg.replace("\n", "\\n")

    LOG.debug(msg)


def _log_debug_response(resp: requests.Response):
    if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
        return

    elapsed = resp.elapsed.total_seconds() * 1000  # Convert to milliseconds
    msg = f"HTTP {resp.status_code} {resp.reason} ({elapsed:.0f} ms): {str(_truncate_response_content(resp))}"

    LOG.debug(msg)


def _truncate_response_content(resp: requests.Response) -> str | bytes:
    try:
        json_data = resp.json()
    except requests.JSONDecodeError:
        if resp.content is not None:
            data = _truncate(resp.content)
        else:
            data = ""
    else:
        if isinstance(json_data, dict):
            data = _truncate(dumps(_sanitize(json_data)))
        else:
            data = _truncate(str(json_data))

    if isinstance(data, bytes):
        return data.replace(b"\n", b"\\n")

    elif isinstance(data, str):
        return data.replace("\n", "\\n")

    return data


def readable_http_error(ex: requests.HTTPError) -> str:
    return readable_http_response(ex.response)


def readable_http_response(resp: requests.Response) -> str:
    return f"{resp.request.method} {resp.url} => {resp.status_code} {resp.reason}: {str(_truncate_response_content(resp))}"


def request_post(
    url: str,
    data: T.Any | None = None,
    json: dict | None = None,
    disable_debug=False,
    **kwargs,
) -> requests.Response:
    global USE_SYSTEM_CERTS

    if not disable_debug:
        _log_debug_request(
            "POST",
            url,
            json=json,
            params=kwargs.get("params"),
            headers=kwargs.get("headers"),
        )

    if USE_SYSTEM_CERTS:
        with requests.Session() as session:
            session.mount("https://", HTTPSystemCertsAdapter())
            resp = session.post(url, data=data, json=json, **kwargs)

    else:
        try:
            resp = requests.post(url, data=data, json=json, **kwargs)
        except requests.exceptions.SSLError as ex:
            if "SSLCertVerificationError" not in str(ex):
                raise ex
            USE_SYSTEM_CERTS = True
            # HTTPSConnectionPool(host='graph.mapillary.com', port=443): Max retries exceeded with url: /login (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1018)')))
            LOG.warning(
                "SSL error occurred, falling back to system SSL certificates: %s", ex
            )
            return request_post(url, data=data, json=json, **kwargs)

    if not disable_debug:
        _log_debug_response(resp)

    return resp


def request_get(
    url: str, params: dict | None = None, disable_debug=False, **kwargs
) -> requests.Response:
    global USE_SYSTEM_CERTS

    if not disable_debug:
        _log_debug_request(
            "GET", url, params=kwargs.get("params"), headers=kwargs.get("headers")
        )

    if USE_SYSTEM_CERTS:
        with requests.Session() as session:
            session.mount("https://", HTTPSystemCertsAdapter())
            resp = session.get(url, params=params, **kwargs)
    else:
        try:
            resp = requests.get(url, params=params, **kwargs)
        except requests.exceptions.SSLError as ex:
            if "SSLCertVerificationError" not in str(ex):
                raise ex
            USE_SYSTEM_CERTS = True
            # HTTPSConnectionPool(host='graph.mapillary.com', port=443): Max retries exceeded with url: /login (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1018)')))
            LOG.warning(
                "SSL error occurred, falling back to system SSL certificates: %s", ex
            )
            resp = request_get(url, params=params, **kwargs)

    if not disable_debug:
        _log_debug_response(resp)

    return resp


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


def get_upload_token(email: str, password: str) -> requests.Response:
    resp = request_post(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/login",
        headers={"Authorization": f"OAuth {MAPILLARY_CLIENT_TOKEN}"},
        json={"email": email, "password": password, "locale": "en_US"},
        timeout=REQUESTS_TIMEOUT,
    )
    resp.raise_for_status()
    return resp


def fetch_organization(
    user_access_token: str, organization_id: int | str
) -> requests.Response:
    resp = request_get(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/{organization_id}",
        params={
            "fields": ",".join(["slug", "description", "name"]),
        },
        headers={
            "Authorization": f"OAuth {user_access_token}",
        },
        timeout=REQUESTS_TIMEOUT,
    )
    resp.raise_for_status()
    return resp


def fetch_user_or_me(
    user_access_token: str, user_id: int | str | None = None
) -> requests.Response:
    if user_id is None:
        url = f"{MAPILLARY_GRAPH_API_ENDPOINT}/me"
    else:
        url = f"{MAPILLARY_GRAPH_API_ENDPOINT}/{user_id}"

    resp = request_get(
        url,
        params={
            "fields": ",".join(["id", "username"]),
        },
        headers={
            "Authorization": f"OAuth {user_access_token}",
        },
        timeout=REQUESTS_TIMEOUT,
    )

    resp.raise_for_status()
    return resp


ActionType = T.Literal[
    "upload_started_upload", "upload_finished_upload", "upload_failed_upload"
]


def log_event(action_type: ActionType, properties: dict) -> requests.Response:
    resp = request_post(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/logging",
        json={"action_type": action_type, "properties": properties},
        headers={
            "Authorization": f"OAuth {MAPILLARY_CLIENT_TOKEN}",
        },
        timeout=REQUESTS_TIMEOUT,
        disable_debug=True,
    )
    resp.raise_for_status()
    return resp


def finish_upload(
    user_access_token: str,
    file_handle: str,
    cluster_filetype: ClusterFileType,
    organization_id: int | str | None = None,
) -> requests.Response:
    data: dict[str, str | int] = {
        "file_handle": file_handle,
        "file_type": cluster_filetype.value,
    }
    if organization_id is not None:
        data["organization_id"] = organization_id

    resp = request_post(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/finish_upload",
        headers={
            "Authorization": f"OAuth {user_access_token}",
        },
        json=data,
        timeout=REQUESTS_TIMEOUT,
    )

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
