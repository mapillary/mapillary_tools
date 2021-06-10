import os
import requests

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
