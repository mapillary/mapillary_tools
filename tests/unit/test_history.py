# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mapillary_tools import history, types


class TestValidateHexdigits:
    def test_valid_md5sum(self):
        # Should not raise
        history._validate_hexdigits("abcdef1234567890")

    def test_valid_short_hex(self):
        history._validate_hexdigits("abcd")

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="Invalid md5sum"):
            history._validate_hexdigits("abc")

    def test_non_hex_raises(self):
        with pytest.raises(ValueError, match="Invalid md5sum"):
            history._validate_hexdigits("xyz123")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid md5sum"):
            history._validate_hexdigits("")


class TestHistoryDescPath:
    def test_returns_path_with_subfolder(self):
        path = history.history_desc_path("aabbccdd")
        assert "aa" in str(path)
        assert path.name == "bbccdd.json"

    def test_long_md5sum(self):
        md5 = "d41d8cd98f00b204e9800998ecf8427e"
        path = history.history_desc_path(md5)
        assert path.name == md5[2:] + ".json"
        assert path.parent.name == "d4"


class TestReadHistoryRecord:
    def test_returns_none_when_no_history_path(self):
        with patch.object(history.constants, "MAPILLARY_UPLOAD_HISTORY_PATH", ""):
            result = history.read_history_record("aabbccdd")
            assert result is None

    def test_returns_none_when_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                history.constants,
                "MAPILLARY_UPLOAD_HISTORY_PATH",
                tmpdir,
            ):
                result = history.read_history_record("aabbccdd")
                assert result is None

    def test_reads_valid_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                history.constants,
                "MAPILLARY_UPLOAD_HISTORY_PATH",
                tmpdir,
            ):
                path = history.history_desc_path("aabbccdd")
                path.parent.mkdir(parents=True, exist_ok=True)
                record = {"params": {"key": "val"}, "summary": {"count": 1}}
                with open(path, "w") as fp:
                    json.dump(record, fp)

                result = history.read_history_record("aabbccdd")
                assert result is not None
                assert result["params"]["key"] == "val"

    def test_returns_none_on_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                history.constants,
                "MAPILLARY_UPLOAD_HISTORY_PATH",
                tmpdir,
            ):
                path = history.history_desc_path("aabbccdd")
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w") as fp:
                    fp.write("not valid json{{{")

                result = history.read_history_record("aabbccdd")
                assert result is None


class TestWriteHistory:
    def test_write_history_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                history.constants,
                "MAPILLARY_UPLOAD_HISTORY_PATH",
                tmpdir,
            ):
                history.write_history(
                    "aabbccdd",
                    params={"user": "test"},
                    summary={"uploaded": 5},
                )
                path = history.history_desc_path("aabbccdd")
                assert path.exists()
                with open(path) as fp:
                    data = json.load(fp)
                assert data["params"]["user"] == "test"
                assert data["summary"]["uploaded"] == 5

    def test_write_history_no_path(self):
        with patch.object(history.constants, "MAPILLARY_UPLOAD_HISTORY_PATH", ""):
            # Should be a no-op
            history.write_history("aabbccdd", params={}, summary={})

    def test_write_history_with_metadatas(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                history.constants,
                "MAPILLARY_UPLOAD_HISTORY_PATH",
                tmpdir,
            ):
                metadata = types.ImageMetadata(
                    time=1000.0,
                    lat=48.0,
                    lon=11.0,
                    alt=100.0,
                    angle=45.0,
                    filename=Path("img.jpg"),
                    MAPFilename="img.jpg",
                )
                history.write_history(
                    "aabbccdd",
                    params={},
                    summary={},
                    metadatas=[metadata],
                )
                path = history.history_desc_path("aabbccdd")
                with open(path) as fp:
                    data = json.load(fp)
                assert "descs" in data
                assert len(data["descs"]) == 1
