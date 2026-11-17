# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import json
import tempfile
import typing as T
from pathlib import Path
from unittest.mock import patch

import pytest
from mapillary_tools import constants, history, types, upload


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


TEST_IMAGE_DIR = Path(__file__).parent.parent.joinpath("data", "images")


def _write_record(md5sum: str, summary: dict, descs: T.Optional[list] = None) -> Path:
    path = history.history_desc_path(md5sum)
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict = {"params": {}, "summary": summary}
    if descs is not None:
        record["descs"] = descs
    path.write_text(json.dumps(record))
    return path


class TestUnfinishedUploads:
    # upload wrote a record with the cluster ID null when finish_upload
    # answered without one, as for an organization that the account is not a
    # member of: nothing was uploaded

    @pytest.fixture(autouse=True)
    def _history_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(tmp_path / "history")
        )

    def test_unfinished_record_is_not_read(self):
        _write_record("a" * 32, {"cluster_id": None, "upload_end_time": 1.0})
        assert history.read_history_record("a" * 32) is None

    @pytest.mark.parametrize(
        "summary",
        [
            # Written before 0.14.0, which added the cluster ID
            {"upload_end_time": 1.0},
            {"cluster_id": "123", "upload_end_time": 1.0},
            # Uploaded with --dry_run
            {"cluster_id": "0", "upload_end_time": 1.0},
        ],
    )
    def test_finished_record_is_read(self, summary: dict):
        _write_record("a" * 32, summary)
        record = history.read_history_record("a" * 32)
        assert record is not None
        assert record["summary"] == summary

    def test_find_uploaded_image_md5s_skips_unfinished_records(self):
        unfinished_image, finished_image = "b" * 32, "c" * 32
        _write_record(
            "a" * 32,
            {"cluster_id": None},
            [{"filetype": "image", "md5sum": unfinished_image}],
        )
        _write_record("d" * 32, {}, [{"filetype": "image", "md5sum": finished_image}])
        assert history.find_uploaded_image_md5s([unfinished_image, finished_image]) == {
            finished_image
        }

    def test_check_upload_history_ignores_unfinished_records(self, tmp_path):
        image_paths = [tmp_path / "first.jpg", tmp_path / "second.jpg"]
        metadatas = []
        for idx, image_path in enumerate(image_paths):
            image_path.write_bytes(f"image {idx}".encode())
            metadatas.append(
                types.ImageMetadata(
                    filename=image_path,
                    lat=1.0,
                    lon=2.0,
                    alt=None,
                    angle=None,
                    time=float(idx),
                    MAPSequenceUUID="sequence",
                )
            )

        def check() -> dict:
            [result] = upload.check_upload_history(
                image_paths, _metadatas_from_process=metadatas
            )
            return result

        sequence_md5sum = check()["sequence_md5sum"]
        image_descs = [
            {"filetype": "image", "md5sum": metadata.md5sum} for metadata in metadatas
        ]
        # Neither the sequence nor its images, also looked up one by one
        _write_record(sequence_md5sum, {"cluster_id": None}, image_descs)
        result = check()
        assert result["already_uploaded"] is False
        assert result["already_uploaded_filenames"] == []

        _write_record(sequence_md5sum, {"cluster_id": "123"}, image_descs)
        assert check()["already_uploaded"] is True

    def test_upload_uploads_unfinished_upload_again(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            constants, "MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN", True
        )
        upload_path = tmp_path / "uploads"
        upload_path.mkdir()
        monkeypatch.setenv("MAPILLARY_UPLOAD_ENDPOINT", str(upload_path))

        image_dir = tmp_path / "images"
        image_dir.mkdir()
        metadatas: list[types.MetadataOrError] = []
        for idx, name in enumerate(["DSC00001.JPG", "DSC00497.JPG"]):
            image_path = image_dir / name
            image_path.write_bytes(TEST_IMAGE_DIR.joinpath(name).read_bytes())
            metadatas.append(
                types.ImageMetadata(
                    filename=image_path,
                    lat=58.5927694 + idx * 0.0001,
                    lon=16.1840944,
                    alt=None,
                    angle=None,
                    time=1613222680.0 + idx,
                    MAPSequenceUUID="sequence",
                    filesize=image_path.stat().st_size,
                )
            )

        def upload_images() -> None:
            upload.upload(
                image_dir,
                {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
                num_upload_workers=1,
                _metadatas_from_process=metadatas,
                dry_run=True,
            )

        upload_images()
        [record_path] = (tmp_path / "history").glob("*/*.json")

        def rewrite_summary(**summary) -> None:
            record = json.loads(record_path.read_text())
            record["summary"] = summary
            record_path.write_text(json.dumps(record))

        # Not finished: uploaded again, and the record replaced
        rewrite_summary(cluster_id=None, upload_end_time=1.0)
        upload_images()
        summary = json.loads(record_path.read_text())["summary"]
        assert summary["cluster_id"] == "0"
        assert summary["upload_end_time"] != 1.0

        # Written before 0.14.0, without a cluster ID: skipped as uploaded
        rewrite_summary(upload_end_time=1.0)
        upload_images()
        assert json.loads(record_path.read_text())["summary"] == {
            "upload_end_time": 1.0
        }
