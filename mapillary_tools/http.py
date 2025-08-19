from __future__ import annotations

import logging

import ssl
import sys
import typing as T
from json import dumps

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

import requests
from requests.adapters import HTTPAdapter


LOG = logging.getLogger(__name__)


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


class Session(requests.Session):
    # NOTE: This is a global flag that affects all Session instances
    USE_SYSTEM_CERTS: T.ClassVar[bool] = False
    # Instance variables
    disable_logging_request: bool = False
    disable_logging_response: bool = False
    # Avoid mounting twice
    _mounted: bool = False

    @override
    def request(self, method: str | bytes, url: str | bytes, *args, **kwargs):
        self._log_debug_request(method, url, *args, **kwargs)

        if Session.USE_SYSTEM_CERTS:
            if not self._mounted:
                self.mount("https://", HTTPSystemCertsAdapter())
                self._mounted = True
            resp = super().request(method, url, *args, **kwargs)
        else:
            try:
                resp = super().request(method, url, *args, **kwargs)
            except requests.exceptions.SSLError as ex:
                if "SSLCertVerificationError" not in str(ex):
                    raise ex
                Session.USE_SYSTEM_CERTS = True
                # HTTPSConnectionPool(host='graph.mapillary.com', port=443): Max retries exceeded with url: /login (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1018)')))
                LOG.warning(
                    "SSL error occurred, falling back to system SSL certificates: %s",
                    ex,
                )
                return self.request(method, url, *args, **kwargs)

        self._log_debug_response(resp)

        return resp

    def _log_debug_request(self, method: str | bytes, url: str | bytes, **kwargs):
        if self.disable_logging_request:
            return

        if not LOG.isEnabledFor(logging.DEBUG):
            return

        if isinstance(method, str) and isinstance(url, str):
            msg = f"HTTP {method} {url}"
        else:
            msg = f"HTTP {method!r} {url!r}"

        if Session.USE_SYSTEM_CERTS:
            msg += " (w/sys_certs)"

        json = kwargs.get("json")
        if json is not None:
            t = _truncate(dumps(_sanitize(json)))
            msg += f" JSON={t}"

        params = kwargs.get("params")
        if params is not None:
            msg += f" PARAMS={_sanitize(params)}"

        headers = kwargs.get("headers")
        if headers is not None:
            msg += f" HEADERS={_sanitize(headers)}"

        timeout = kwargs.get("timeout")
        if timeout is not None:
            msg += f" TIMEOUT={timeout}"

        msg = msg.replace("\n", "\\n")

        LOG.debug(msg)

    def _log_debug_response(self, resp: requests.Response):
        if self.disable_logging_response:
            return

        if not LOG.isEnabledFor(logging.DEBUG):
            return

        elapsed = resp.elapsed.total_seconds() * 1000  # Convert to milliseconds
        msg = f"HTTP {resp.status_code} {resp.reason} ({elapsed:.0f} ms): {str(_truncate_response_content(resp))}"

        LOG.debug(msg)


def readable_http_error(ex: requests.HTTPError) -> str:
    return readable_http_response(ex.response)


def readable_http_response(resp: requests.Response) -> str:
    return f"{resp.request.method} {resp.url} => {resp.status_code} {resp.reason}: {str(_truncate_response_content(resp))}"


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
