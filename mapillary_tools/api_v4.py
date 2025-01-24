import logging
import os
import ssl
import typing as T

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


def request_post(
    url: str,
    data: T.Optional[T.Any] = None,
    json: T.Optional[dict] = None,
    **kwargs,
) -> requests.Response:
    global USE_SYSTEM_CERTS

    if USE_SYSTEM_CERTS:
        with requests.Session() as session:
            session.mount("https://", HTTPSystemCertsAdapter())
            return session.post(url, data=data, json=json, **kwargs)

    else:
        try:
            return requests.post(url, data=data, json=json, **kwargs)
        except requests.exceptions.SSLError as ex:
            if "SSLCertVerificationError" not in str(ex):
                raise ex
            USE_SYSTEM_CERTS = True
            # HTTPSConnectionPool(host='graph.mapillary.com', port=443): Max retries exceeded with url: /login (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1018)')))
            LOG.warning(
                "SSL error occurred, falling back to system SSL certificates: %s", ex
            )
            with requests.Session() as session:
                session.mount("https://", HTTPSystemCertsAdapter())
                return session.post(url, data=data, json=json, **kwargs)


def request_get(
    url: str,
    params: T.Optional[dict] = None,
    **kwargs,
) -> requests.Response:
    global USE_SYSTEM_CERTS

    if USE_SYSTEM_CERTS:
        with requests.Session() as session:
            session.mount("https://", HTTPSystemCertsAdapter())
            return session.get(url, params=params, **kwargs)
    else:
        try:
            return requests.get(url, params=params, **kwargs)
        except requests.exceptions.SSLError as ex:
            if "SSLCertVerificationError" not in str(ex):
                raise ex
            USE_SYSTEM_CERTS = True
            # HTTPSConnectionPool(host='graph.mapillary.com', port=443): Max retries exceeded with url: /login (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1018)')))
            LOG.warning(
                "SSL error occurred, falling back to system SSL certificates: %s", ex
            )
            with requests.Session() as session:
                session.mount("https://", HTTPSystemCertsAdapter())
                return session.get(url, params=params, **kwargs)


def get_upload_token(email: str, password: str) -> requests.Response:
    resp = request_post(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/login",
        params={"access_token": MAPILLARY_CLIENT_TOKEN},
        json={"email": email, "password": password, "locale": "en_US"},
        timeout=REQUESTS_TIMEOUT,
    )
    resp.raise_for_status()
    return resp


def fetch_organization(
    user_access_token: str, organization_id: T.Union[int, str]
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


ActionType = T.Literal[
    "upload_started_upload", "upload_finished_upload", "upload_failed_upload"
]


def log_event(action_type: ActionType, properties: T.Dict) -> requests.Response:
    resp = request_post(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/logging",
        json={
            "action_type": action_type,
            "properties": properties,
        },
        headers={
            "Authorization": f"OAuth {MAPILLARY_CLIENT_TOKEN}",
        },
        timeout=REQUESTS_TIMEOUT,
    )
    resp.raise_for_status()
    return resp
