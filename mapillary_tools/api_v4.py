import os
import requests

MAPILLARY_WEB_CLIENT_ID = os.getenv(
    "MAPILLARY_WEB_CLIENT_ID", "MkJKbDA0bnZuZlcxeTJHTmFqN3g1dzo1YTM0NjRkM2EyZGU5MzBh"
)
MAPILLARY_GRAPH_API_ENDPOINT = os.getenv(
    "MAPILLARY_GRAPH_API_ENDPOINT", "https://a.mapillary.com/v4"
)


def get_upload_token(email: str, password: str) -> dict:
    resp = requests.post(
        f"{MAPILLARY_GRAPH_API_ENDPOINT}/login",
        params={"access_token": MAPILLARY_WEB_CLIENT_ID},
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.json()
