# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from unittest.mock import MagicMock

import pytest
import requests

from mapillary_tools import api_v4


class TestCreateSessions:
    def test_create_user_session_sets_oauth_header(self):
        session = api_v4.create_user_session("test_token_123")
        assert session.headers["Authorization"] == "OAuth test_token_123"

    def test_create_client_session_sets_oauth_header(self):
        session = api_v4.create_client_session()
        assert session.headers["Authorization"].startswith("OAuth ")


class TestIsAuthError:
    def _make_response(self, status_code: int, json_data=None):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = status_code
        if json_data is not None:
            resp.json.return_value = json_data
        else:
            resp.json.side_effect = Exception("no json")
        return resp

    def test_401_is_auth_error(self):
        resp = self._make_response(401)
        assert api_v4.is_auth_error(resp) is True

    def test_403_is_auth_error(self):
        resp = self._make_response(403)
        assert api_v4.is_auth_error(resp) is True

    def test_400_with_not_authorized_type(self):
        resp = self._make_response(
            400,
            json_data={"debug_info": {"type": "NotAuthorizedError"}},
        )
        assert api_v4.is_auth_error(resp) is True

    def test_400_without_auth_type(self):
        resp = self._make_response(
            400,
            json_data={"debug_info": {"type": "SomeOtherError"}},
        )
        assert api_v4.is_auth_error(resp) is False

    def test_400_no_json(self):
        resp = self._make_response(400)
        assert api_v4.is_auth_error(resp) is False

    def test_200_is_not_auth_error(self):
        resp = self._make_response(200)
        assert api_v4.is_auth_error(resp) is False

    def test_500_is_not_auth_error(self):
        resp = self._make_response(500)
        assert api_v4.is_auth_error(resp) is False


class TestExtractAuthErrorMessage:
    def _make_auth_response(self, status_code: int, json_data=None, text: str = ""):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = status_code
        resp.text = text
        if json_data is not None:
            resp.json.return_value = json_data
        else:
            resp.json.side_effect = Exception("no json")
        return resp

    def test_graph_api_error_message(self):
        resp = self._make_auth_response(
            401,
            json_data={"error": {"message": "Invalid token"}},
        )
        assert api_v4.extract_auth_error_message(resp) == "Invalid token"

    def test_upload_service_error_message(self):
        resp = self._make_auth_response(
            403,
            json_data={"debug_info": {"message": "Forbidden access"}},
        )
        assert api_v4.extract_auth_error_message(resp) == "Forbidden access"

    def test_fallback_to_text(self):
        resp = self._make_auth_response(
            401,
            json_data={},
            text="Unauthorized",
        )
        assert api_v4.extract_auth_error_message(resp) == "Unauthorized"

    def test_no_json_fallback(self):
        resp = self._make_auth_response(
            401,
            text="Auth failed",
        )
        assert api_v4.extract_auth_error_message(resp) == "Auth failed"


class TestJsonifyResponse:
    def test_invalid_json_raises_http_content_error(self):
        resp = MagicMock(spec=requests.Response)
        resp.json.side_effect = requests.JSONDecodeError("err", "", 0)
        with pytest.raises(api_v4.HTTPContentError) as exc_info:
            api_v4.jsonify_response(resp)
        assert exc_info.value.response is resp
