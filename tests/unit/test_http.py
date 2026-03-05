# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from unittest.mock import MagicMock

import requests

from mapillary_tools import http


class TestTruncate:
    def test_short_string_unchanged(self):
        assert http._truncate("hello") == "hello"

    def test_long_string_truncated(self):
        s = "a" * 300
        result = http._truncate(s, limit=256)
        assert len(result) < 300
        assert "truncated" in result
        assert "44 chars truncated" in result

    def test_short_bytes_unchanged(self):
        assert http._truncate(b"hello") == b"hello"

    def test_long_bytes_utf8_decodable_truncated(self):
        b = b"a" * 300
        result = http._truncate(b, limit=256)
        assert isinstance(result, str)
        assert "truncated" in result

    def test_long_bytes_not_utf8_decodable(self):
        b = bytes(range(256)) * 2  # 512 bytes, not valid utf-8
        result = http._truncate(b, limit=256)
        assert isinstance(result, bytes)
        assert b"truncated" in result

    def test_exact_limit_not_truncated(self):
        s = "a" * 256
        result = http._truncate(s, limit=256)
        assert result == s


class TestSanitize:
    def test_authorization_redacted(self):
        result = http._sanitize({"Authorization": "Bearer secret_token"})
        assert result["Authorization"] == "[REDACTED]"

    def test_cookie_redacted(self):
        result = http._sanitize({"Cookie": "session=abc123"})
        assert result["Cookie"] == "[REDACTED]"

    def test_access_token_underscore_redacted(self):
        result = http._sanitize({"access_token": "tok123"})
        assert result["access_token"] == "[REDACTED]"

    def test_access_token_hyphen_redacted(self):
        result = http._sanitize({"Access-Token": "tok123"})
        assert result["Access-Token"] == "[REDACTED]"

    def test_x_fb_access_token_redacted(self):
        result = http._sanitize({"X-FB-Access-Token": "tok456"})
        assert result["X-FB-Access-Token"] == "[REDACTED]"

    def test_user_upload_token_redacted(self):
        result = http._sanitize({"user_upload_token": "tok789"})
        assert result["user_upload_token"] == "[REDACTED]"

    def test_password_redacted(self):
        result = http._sanitize({"password": "secret"})
        assert result["password"] == "[REDACTED]"

    def test_non_sensitive_header_kept(self):
        result = http._sanitize({"Content-Type": "application/json"})
        assert result["Content-Type"] == "application/json"

    def test_long_value_truncated(self):
        result = http._sanitize({"X-Data": "x" * 500})
        assert "truncated" in result["X-Data"]

    def test_non_string_value_kept(self):
        result = http._sanitize({"X-Count": 42})
        assert result["X-Count"] == 42


class TestTruncateResponseContent:
    def _make_response(
        self, content: bytes = b"", json_data=None, status_code: int = 200
    ):
        resp = MagicMock(spec=requests.Response)
        resp.content = content
        resp.status_code = status_code
        if json_data is not None:
            resp.json.return_value = json_data
        else:
            resp.json.side_effect = requests.JSONDecodeError("", "", 0)
        return resp

    def test_json_dict_response_sanitized_and_serialized(self):
        resp = self._make_response(json_data={"key": "value"})
        result = http._truncate_response_content(resp)
        assert isinstance(result, str)
        assert '"key"' in result
        assert '"value"' in result

    def test_json_dict_with_sensitive_keys_redacted(self):
        resp = self._make_response(json_data={"authorization": "secret", "data": "ok"})
        result = http._truncate_response_content(resp)
        assert "[REDACTED]" in result
        assert "secret" not in result

    def test_json_non_dict_response(self):
        resp = self._make_response(json_data=[1, 2, 3])
        result = http._truncate_response_content(resp)
        assert "[1, 2, 3]" in str(result)

    def test_non_json_response_returns_bytes(self):
        resp = self._make_response(content=b"plain text response")
        result = http._truncate_response_content(resp)
        # _truncate on short bytes returns bytes unchanged
        assert isinstance(result, bytes)
        assert result == b"plain text response"

    def test_non_json_response_no_content(self):
        resp = self._make_response(content=None)
        result = http._truncate_response_content(resp)
        assert result == ""

    def test_newlines_replaced_in_str_result(self):
        resp = self._make_response(json_data={"key": "line1\nline2"})
        result = http._truncate_response_content(resp)
        assert isinstance(result, str)
        assert "\n" not in result
        assert "\\n" in result

    def test_newlines_replaced_in_bytes_result(self):
        resp = self._make_response(content=b"line1\nline2")
        result = http._truncate_response_content(resp)
        assert isinstance(result, bytes)
        assert b"\n" not in result
        assert b"\\n" in result
