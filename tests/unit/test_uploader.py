import typing as T
from pathlib import Path
import dataclasses
import concurrent.futures
from unittest.mock import patch

import py.path

import pytest

from mapillary_tools import api_v4, uploader
from mapillary_tools.serializer import description

from ..integration.fixtures import extract_all_uploaded_descs, setup_upload


IMPORT_PATH = "tests/unit/data"


@pytest.fixture
def setup_unittest_data(tmpdir: py.path.local):
    data_path = tmpdir.mkdir("data")
    source = py.path.local(IMPORT_PATH)
    source.copy(data_path)
    yield data_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


def test_upload_images(setup_unittest_data: py.path.local, setup_upload: py.path.local):
    mly_uploader = uploader.Uploader(
        uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"}, dry_run=True
        )
    )
    test_exif = setup_unittest_data.join("test_exif.jpg")
    descs: T.List[description.DescriptionOrError] = [
        {
            "MAPLatitude": 58.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": str(test_exif),
            "md5sum": None,
            "filetype": "image",
        },
        {
            "MAPLatitude": 59.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_25_41_140",
            "filename": str(test_exif),
            "md5sum": "hello",
            "filetype": "image",
        },
    ]
    results = list(
        uploader.ZipUploader.zip_images_and_upload(
            mly_uploader,
            [
                description.DescriptionJSONSerializer.from_desc(T.cast(T.Any, desc))
                for desc in descs
            ],
        )
    )
    assert len(results) == 1
    actual_descs = sum(extract_all_uploaded_descs(Path(setup_upload)), [])
    assert 1 == len(actual_descs), (
        f"should return 1 desc because of the unique filename but got {actual_descs}"
    )


def test_upload_images_multiple_sequences(
    setup_unittest_data: py.path.local, setup_upload: py.path.local
):
    test_exif = setup_unittest_data.join("test_exif.jpg")
    fixed_exif = setup_unittest_data.join("fixed_exif.jpg")
    descs: T.List[description.DescriptionOrError] = [
        {
            "MAPLatitude": 58.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": str(test_exif),
            "md5sum": None,
            "filetype": "image",
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 54.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": str(test_exif),
            "md5sum": None,
            "filetype": "image",
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 59.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_25_41_140",
            "filename": str(fixed_exif),
            "md5sum": None,
            "filetype": "image",
            "MAPSequenceUUID": "sequence_2",
        },
    ]
    mly_uploader = uploader.Uploader(
        uploader.UploadOptions(
            {
                "user_upload_token": "YOUR_USER_ACCESS_TOKEN",
                # will call the API for real
                # "MAPOrganizationKey": "3011753992432185",
            },
            dry_run=True,
        ),
    )
    results = list(
        uploader.ZipUploader.zip_images_and_upload(
            mly_uploader,
            [
                description.DescriptionJSONSerializer.from_desc(T.cast(T.Any, desc))
                for desc in descs
            ],
        )
    )
    assert len(results) == 2
    actual_descs = sum(extract_all_uploaded_descs(Path(setup_upload)), [])
    assert 2 == len(actual_descs)


def test_upload_zip(
    setup_unittest_data: py.path.local, setup_upload: py.path.local, emitter=None
):
    test_exif = setup_unittest_data.join("test_exif.jpg")
    setup_unittest_data.join("another_directory").mkdir()
    test_exif2 = setup_unittest_data.join("another_directory").join("test_exif.jpg")
    test_exif.copy(test_exif2)

    descs: T.List[description.DescriptionOrError] = [
        {
            "MAPLatitude": 58.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": str(test_exif),
            "md5sum": "1",
            "filetype": "image",
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 54.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": str(test_exif2),
            "md5sum": "2",
            "filetype": "image",
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 59.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_25_41_140",
            "filename": str(test_exif),
            "md5sum": "3",
            "filetype": "image",
            "MAPSequenceUUID": "sequence_2",
        },
    ]
    zip_dir = setup_unittest_data.mkdir("zip_dir")
    uploader.ZipUploader.zip_images(
        [
            description.DescriptionJSONSerializer.from_desc(T.cast(T.Any, desc))
            for desc in descs
        ],
        Path(zip_dir),
    )
    assert len(zip_dir.listdir()) == 2, list(zip_dir.listdir())

    mly_uploader = uploader.Uploader(
        uploader.UploadOptions(
            {
                "user_upload_token": "YOUR_USER_ACCESS_TOKEN",
                # will call the API for real
                # "MAPOrganizationKey": 3011753992432185,
            },
            dry_run=True,
        ),
        emitter=emitter,
    )
    for zip_path in zip_dir.listdir():
        cluster = uploader.ZipUploader._upload_zipfile(mly_uploader, Path(zip_path))
        assert cluster == "0"
    actual_descs = sum(extract_all_uploaded_descs(Path(setup_upload)), [])
    assert 3 == len(actual_descs)


def test_upload_blackvue(tmpdir: py.path.local, setup_upload: py.path.local):
    mly_uploader = uploader.Uploader(
        uploader.UploadOptions(
            {
                "user_upload_token": "YOUR_USER_ACCESS_TOKEN",
                # will call the API for real
                # "MAPOrganizationKey": "3011753992432185",
            },
            dry_run=True,
        )
    )
    blackvue_path = tmpdir.join("blackvue.mp4")
    with open(blackvue_path, "wb") as fp:
        fp.write(b"this is a fake video")
    with Path(blackvue_path).open("rb") as fp:
        file_handle = mly_uploader.upload_stream(
            fp,
            session_key="this_is_a_blackvue.mp4",
        )
    cluster_id = mly_uploader.finish_upload(
        file_handle, api_v4.ClusterFileType.BLACKVUE
    )
    assert cluster_id == "0"
    assert setup_upload.join("this_is_a_blackvue.mp4").exists()
    with open(setup_upload.join("this_is_a_blackvue.mp4"), "rb") as fp:
        assert fp.read() == b"this is a fake video"


def test_upload_zip_with_emitter(
    setup_unittest_data: py.path.local, setup_upload: py.path.local
):
    emitter = uploader.EventEmitter()

    stats = {}

    @emitter.on("upload_start")
    def _upload_start(payload):
        assert payload["entity_size"] > 0
        assert "offset" not in payload
        assert "test_started" not in payload
        payload["test_started"] = True

        assert payload["sequence_md5sum"] not in stats
        stats[payload["sequence_md5sum"]] = {**payload}

    @emitter.on("upload_fetch_offset")
    def _fetch_offset(payload):
        assert payload["offset"] >= 0
        assert payload["test_started"]
        payload["test_fetch_offset"] = True

        assert payload["sequence_md5sum"] in stats

    @emitter.on("upload_end")
    def _upload_end(payload):
        assert payload["offset"] > 0
        assert payload["test_started"]
        assert payload["test_fetch_offset"]

        assert payload["sequence_md5sum"] in stats

    test_upload_zip(setup_unittest_data, setup_upload, emitter=emitter)

    assert len(stats) == 2, stats


class TestSingleImageUploader:
    """Test suite for SingleImageUploader with focus on multithreading scenarios."""

    def test_single_image_uploader_basic(
        self, setup_unittest_data: py.path.local, setup_upload: py.path.local
    ):
        """Test basic functionality of SingleImageUploader."""

        upload_options = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"}
        )
        single_uploader = self._create_image_uploader_with_cache_enabled(upload_options)

        # Create a mock image metadata
        test_exif = setup_unittest_data.join("test_exif.jpg")
        image_metadata = description.DescriptionJSONSerializer.from_desc(
            {
                "MAPLatitude": 58.5927694,
                "MAPLongitude": 16.1840944,
                "MAPCaptureTime": "2021_02_13_13_24_41_140",
                "filename": str(test_exif),
                "md5sum": "test_md5",
                "filetype": "image",
            }
        )

        # Use actual user session
        with api_v4.create_user_session(
            upload_options.user_items["user_upload_token"]
        ) as user_session:
            # Test upload
            image_progress: dict = {}
            file_handle = single_uploader.upload(
                user_session, image_metadata, image_progress
            )

            assert file_handle is not None
            assert isinstance(file_handle, str)

    def test_single_image_uploader_multithreading(
        self, setup_unittest_data: py.path.local, setup_upload: py.path.local
    ):
        """Test that SingleImageUploader works correctly with multiple threads including cache thread safety."""
        upload_options = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            num_upload_workers=4,
        )

        # Create a single instance to be shared across threads
        single_uploader = self._create_image_uploader_with_cache_enabled(upload_options)

        test_exif = setup_unittest_data.join("test_exif.jpg")
        num_workers = 64

        def upload_image(thread_id):
            # Each thread uploads a different "image" (different metadata)
            image_metadata = description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927694 + thread_id * 0.001,
                    "MAPLongitude": 16.1840944 + thread_id * 0.001,
                    "MAPCaptureTime": f"2021_02_13_13_{(24 + thread_id) % 60:02d}_41_140",
                    "filename": str(test_exif),
                    "md5sum": f"test_md5_{thread_id}",
                    "filetype": "image",
                }
            )

            # Use actual user session for each thread
            with api_v4.create_user_session(
                upload_options.user_items["user_upload_token"]
            ) as user_session:
                image_progress = {"thread_id": thread_id}

                # Test cache operations for thread safety
                cache_key = f"thread_{thread_id}_key"
                cached_handle = single_uploader._get_cached_file_handle(cache_key)

                file_handle = single_uploader.upload(
                    user_session, image_metadata, image_progress
                )

                # Test cache write thread safety
                single_uploader._set_file_handle_cache(cache_key, f"handle_{thread_id}")

                # Verify result
                assert file_handle is not None, (
                    f"Thread {thread_id} got None file handle"
                )
                assert isinstance(file_handle, str), (
                    f"Thread {thread_id} got non-string file handle"
                )

                return file_handle

        # Use ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(upload_image, i) for i in range(num_workers)]

            # Collect results - let exceptions propagate
            file_handles = [future.result() for future in futures]

        # Verify all uploads succeeded
        assert len(file_handles) == num_workers, (
            f"Expected {num_workers} results, got {len(file_handles)}"
        )
        assert all(handle is not None for handle in file_handles), (
            "Some uploads returned None"
        )

        # Verify all thread-specific cache entries exist (cache thread safety)
        for i in range(num_workers):
            cached_value = single_uploader._get_cached_file_handle(f"thread_{i}_key")
            assert cached_value == f"handle_{i}", f"Cache corrupted for thread {i}"

    def test_single_image_uploader_cache_disabled(
        self, setup_unittest_data: py.path.local, setup_upload: py.path.local
    ):
        """Test SingleImageUploader behavior when cache is disabled."""
        # Test with cache disabled (dry_run=True but no cache dir)
        with patch("mapillary_tools.constants.UPLOAD_CACHE_DIR", None):
            upload_options = uploader.UploadOptions(
                {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"}
            )

            single_uploader = self._create_image_uploader_with_cache_disabled(
                upload_options
            )

            # Upload should still work without cache
            test_exif = setup_unittest_data.join("test_exif.jpg")
            image_metadata = description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927694,
                    "MAPLongitude": 16.1840944,
                    "MAPCaptureTime": "2021_02_13_13_24_41_140",
                    "filename": str(test_exif),
                    "md5sum": "no_cache_test",
                    "filetype": "image",
                }
            )

            with api_v4.create_user_session(
                upload_options.user_items["user_upload_token"]
            ) as user_session:
                image_progress: dict = {}

                file_handle = single_uploader.upload(
                    user_session, image_metadata, image_progress
                )
                assert file_handle is not None, "Upload should work even without cache"

                # Cache operations should be no-ops
                cached_handle = single_uploader._get_cached_file_handle("any_key")
                assert cached_handle is None, "Should return None when cache disabled"

                # Set cache should not raise exception
                single_uploader._set_file_handle_cache(
                    "any_key", "any_value"
                )  # Should not crash

    def _create_image_uploader_with_cache_enabled(
        self, upload_options: uploader.UploadOptions
    ):
        upload_options_to_enable_cache = dataclasses.replace(
            upload_options, dry_run=False
        )

        # Single shared instance with cache
        single_uploader = uploader.SingleImageUploader(upload_options_to_enable_cache)
        assert single_uploader.cache is not None, "Cache should be enabled"

        single_uploader.upload_options = dataclasses.replace(
            upload_options, dry_run=True
        )

        return single_uploader

    def _create_image_uploader_with_cache_disabled(
        self, upload_options: uploader.UploadOptions
    ):
        upload_options_to_disable_cache = dataclasses.replace(
            upload_options, dry_run=True
        )

        # Single shared instance without cache
        single_uploader = uploader.SingleImageUploader(upload_options_to_disable_cache)
        assert single_uploader.cache is None, "Cache should be disabled"

        return single_uploader
