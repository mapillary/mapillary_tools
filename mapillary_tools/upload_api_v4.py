import requests
import os

from .api_v4 import MAPILLARY_GRAPH_API_ENDPOINT

MAPILLARY_UPLOAD_ENDPOINT = os.getenv(
    "MAPILLARY_UPLOAD_ENDPOINT", "https://rupload.facebook.com/mapillary_public_uploads"
)


class UploadService:
    access_token: str

    def __init__(self, access_token: str):
        self.access_token = access_token

    def fetch_offset(self, session_key: str) -> int:
        headers = {
            "Authorization": f"OAuth {self.access_token}",
        }
        resp = requests.get(
            f"{MAPILLARY_UPLOAD_ENDPOINT}/{session_key}", headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        return data["offset"]

    def upload(self, session_key: str, data_size: int, data) -> requests.Response:
        headers = {
            "Authorization": f"OAuth {self.access_token}",
            "Offset": "0",
            "X-Entity-Type": "application/zip",
            "X-Entity-Length": str(data_size),
            "X-Entity-Name": session_key,
        }
        return requests.post(
            f"{MAPILLARY_UPLOAD_ENDPOINT}/{session_key}", headers=headers, data=data
        )

    def finish(self, file_handle: str) -> requests.Response:
        headers = {
            "Authorization": f"OAuth {self.access_token}",
        }
        json = {
            "file_handle": file_handle,
        }
        return requests.post(
            f"{MAPILLARY_GRAPH_API_ENDPOINT}/finish_upload", headers=headers, json=json
        )
