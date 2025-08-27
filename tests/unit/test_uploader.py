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
        self, setup_unittest_data: py.path.local
    ):
        """Test that SingleImageUploader works correctly with multiple threads including cache thread safety."""
        upload_options = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            num_upload_workers=4,
        )

        # Create a single instance to be shared across threads
        single_uploader = self._create_image_uploader_with_cache_enabled(upload_options)

        # Verify cache is available
        assert single_uploader.cache is not None, (
            "SingleImageUploader should have cache enabled"
        )

        test_exif = setup_unittest_data.join("test_exif.jpg")
        num_workers = 64

        # Test direct cache operations before multithreading
        pre_threading_cache_keys = []
        for i in range(5):
            key = f"pre_threading_key_{i}"
            value = f"pre_threading_value_{i}"
            single_uploader.cache.set(key, value)
            pre_threading_cache_keys.append((key, value))

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
                single_uploader._get_cached_file_handle(cache_key)

                file_handle = single_uploader.upload(
                    user_session, image_metadata, image_progress
                )

                # Test cache write thread safety via exposed cache instance
                assert single_uploader.cache is not None, (
                    "Cache should not be None in thread"
                )
                single_uploader.cache.set(cache_key, f"handle_{thread_id}")

                # Also test via the _set_file_handle_cache method
                another_key = f"thread_{thread_id}_another_key"
                single_uploader._set_file_handle_cache(
                    another_key, f"another_handle_{thread_id}"
                )

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

        # Verify cache integrity after multithreading
        # 1. Check pre-threading cache entries are still intact
        for key, expected_value in pre_threading_cache_keys:
            actual_value = single_uploader.cache.get(key)
            assert actual_value == expected_value, (
                f"Pre-threading cache entry corrupted: {key}. Expected: {expected_value}, Got: {actual_value}"
            )

        # 2. Check all thread-specific cache entries exist (cache thread safety)
        for i in range(num_workers):
            cached_value = single_uploader._get_cached_file_handle(f"thread_{i}_key")
            assert cached_value == f"handle_{i}", f"Cache corrupted for thread {i}"

            # Also check entries set via exposed cache instance
            direct_cached_value = single_uploader.cache.get(f"thread_{i}_key")
            assert direct_cached_value == f"handle_{i}", (
                f"Direct cache access failed for thread {i}"
            )

            # Check entries set via _set_file_handle_cache
            another_cached_value = single_uploader._get_cached_file_handle(
                f"thread_{i}_another_key"
            )
            assert another_cached_value == f"another_handle_{i}", (
                f"Another cache entry corrupted for thread {i}"
            )

        # Test post-threading cache operations
        post_threading_test_key = "post_threading_test"
        post_threading_test_value = "post_threading_value"

        single_uploader.cache.set(post_threading_test_key, post_threading_test_value)
        retrieved_post_threading = single_uploader.cache.get(post_threading_test_key)
        assert retrieved_post_threading == post_threading_test_value, (
            "Post-threading cache operations failed"
        )

    def test_single_image_uploader_cache_disabled(
        self, setup_unittest_data: py.path.local
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

            # Verify cache is disabled by checking the exposed cache property
            assert single_uploader.cache is None, "Cache should be disabled"

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

                assert file_handle is not None, "Upload should work without cache"
                assert isinstance(file_handle, str), "File handle should be a string"

            # Test that cache operations safely handle None cache
            test_key = "test_no_cache_operations"
            test_value = "test_value_should_be_ignored"

            # These should safely do nothing when cache is None
            single_uploader._set_file_handle_cache(test_key, test_value)
            retrieved_value = single_uploader._get_cached_file_handle(test_key)

            assert retrieved_value is None, (
                "Cache operations should return None when cache is disabled"
            )

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


class TestImageSequenceUploader:
    """Test suite for ImageSequenceUploader with focus on multithreading scenarios and caching."""

    def test_image_sequence_uploader_basic(self, setup_unittest_data: py.path.local):
        """Test basic functionality of ImageSequenceUploader."""
        upload_options = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            dry_run=True,
        )
        emitter = uploader.EventEmitter()
        sequence_uploader = uploader.ImageSequenceUploader(upload_options, emitter)

        # Create mock image metadata for a single sequence
        test_exif = setup_unittest_data.join("test_exif.jpg")
        image_metadatas = [
            description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927694,
                    "MAPLongitude": 16.1840944,
                    "MAPCaptureTime": "2021_02_13_13_24_41_140",
                    "filename": str(test_exif),
                    "md5sum": "test_md5_1",
                    "filetype": "image",
                    "MAPSequenceUUID": "sequence_1",
                }
            ),
            description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927695,
                    "MAPLongitude": 16.1840945,
                    "MAPCaptureTime": "2021_02_13_13_24_42_140",
                    "filename": str(test_exif),
                    "md5sum": "test_md5_2",
                    "filetype": "image",
                    "MAPSequenceUUID": "sequence_1",
                }
            ),
        ]

        # Test upload
        results = list(sequence_uploader.upload_images(image_metadatas))

        assert len(results) == 1
        sequence_uuid, upload_result = results[0]
        assert sequence_uuid == "sequence_1"
        assert upload_result.error is None
        assert upload_result.result is not None

    def test_image_sequence_uploader_multithreading_with_cache_enabled(
        self, setup_unittest_data: py.path.local
    ):
        """Test that ImageSequenceUploader's internal multithreading works correctly when cache is enabled."""
        # Create upload options that enable cache
        upload_options_with_cache = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            num_upload_workers=4,  # This will be used internally for parallel image uploads
            dry_run=False,  # Cache requires dry_run=False initially
        )
        emitter = uploader.EventEmitter()
        sequence_uploader = uploader.ImageSequenceUploader(
            upload_options_with_cache, emitter
        )

        # Override to dry_run=True for actual testing
        sequence_uploader.upload_options = dataclasses.replace(
            upload_options_with_cache, dry_run=True
        )
        sequence_uploader.single_image_uploader.upload_options = dataclasses.replace(
            upload_options_with_cache, dry_run=True
        )

        # Verify cache is available and shared
        assert sequence_uploader.cache is not None, (
            "ImageSequenceUploader should have cache enabled"
        )
        assert (
            sequence_uploader.single_image_uploader.cache is sequence_uploader.cache
        ), "SingleImageUploader should share the same cache instance"

        test_exif = setup_unittest_data.join("test_exif.jpg")

        num_images = 100  # Reasonable number for testing with direct cache verification
        image_metadatas = []

        for i in range(num_images):
            image_metadatas.append(
                description.DescriptionJSONSerializer.from_desc(
                    {
                        "MAPLatitude": 58.5927694 + i * 0.0001,
                        "MAPLongitude": 16.1840944 + i * 0.0001,
                        "MAPCaptureTime": f"2021_02_13_13_{(24 + i) % 60:02d}_{(41 + i) % 60:02d}_140",
                        "filename": str(test_exif),
                        "md5sum": f"multi_thread_test_md5_{i}",
                        "filetype": "image",
                        "MAPSequenceUUID": "multi_thread_sequence",
                    }
                )
            )

        # Test upload - this will internally use multithreading via _upload_images_parallel
        results = list(sequence_uploader.upload_images(image_metadatas))

        assert len(results) == 1, f"Expected 1 sequence result, got {len(results)}"
        sequence_uuid, upload_result = results[0]
        assert sequence_uuid == "multi_thread_sequence", (
            f"Got wrong sequence UUID: {sequence_uuid}"
        )
        assert upload_result.error is None, (
            f"Upload failed with error: {upload_result.error}"
        )
        assert upload_result.result is not None, "Upload should return a cluster ID"

        # Test direct cache operations using exposed cache instance
        test_key = "test_multithreading_cache_key"
        test_value = "test_multithreading_file_handle"

        # Set via sequence uploader cache
        sequence_uploader.cache.set(test_key, test_value)

        # Get via single image uploader cache (same instance)
        assert sequence_uploader.single_image_uploader.cache is not None, (
            "Single image uploader cache should not be None"
        )
        retrieved_via_single = sequence_uploader.single_image_uploader.cache.get(
            test_key
        )
        assert retrieved_via_single == test_value, (
            f"Cache sharing failed. Expected: {test_value}, Got: {retrieved_via_single}"
        )

        # Test cache manipulation by setting different values via different references
        test_key_2 = "test_cache_manipulation"
        test_value_sequence = "value_from_sequence_uploader"
        test_value_single = "value_from_single_uploader"

        # Set via sequence uploader
        sequence_uploader.cache.set(test_key_2, test_value_sequence)
        assert (
            sequence_uploader.single_image_uploader.cache.get(test_key_2)
            == test_value_sequence
        )

        # Override via single image uploader (same cache instance)
        sequence_uploader.single_image_uploader.cache.set(test_key_2, test_value_single)
        assert sequence_uploader.cache.get(test_key_2) == test_value_single, (
            "Cache instances should be the same object"
        )

    def test_image_sequence_uploader_multithreading_with_cache_disabled(
        self, setup_unittest_data: py.path.local
    ):
        """Test that ImageSequenceUploader's internal multithreading works correctly when cache is disabled."""
        # Test with cache disabled via constants patch
        with patch("mapillary_tools.constants.UPLOAD_CACHE_DIR", None):
            upload_options = uploader.UploadOptions(
                {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
                num_upload_workers=4,  # This will be used internally for parallel image uploads
                dry_run=True,
            )
            emitter = uploader.EventEmitter()
            sequence_uploader = uploader.ImageSequenceUploader(upload_options, emitter)

            # Verify cache is disabled for both instances
            assert sequence_uploader.cache is None, (
                "ImageSequenceUploader should have cache disabled"
            )
            assert sequence_uploader.single_image_uploader.cache is None, (
                "SingleImageUploader should also have cache disabled"
            )

            test_exif = setup_unittest_data.join("test_exif.jpg")

            num_images = 100
            image_metadatas = []

            for i in range(num_images):
                image_metadatas.append(
                    description.DescriptionJSONSerializer.from_desc(
                        {
                            "MAPLatitude": 59.5927694 + i * 0.0001,
                            "MAPLongitude": 17.1840944 + i * 0.0001,
                            "MAPCaptureTime": f"2021_02_13_14_{(24 + i) % 60:02d}_{(41 + i) % 60:02d}_140",
                            "filename": str(test_exif),
                            "md5sum": f"no_cache_multi_thread_md5_{i}",
                            "filetype": "image",
                            "MAPSequenceUUID": "no_cache_multi_thread_sequence",
                        }
                    )
                )

            # Test upload - this will internally use multithreading via _upload_images_parallel
            results = list(sequence_uploader.upload_images(image_metadatas))

            assert len(results) == 1, f"Expected 1 sequence result, got {len(results)}"
            sequence_uuid, upload_result = results[0]
            assert sequence_uuid == "no_cache_multi_thread_sequence", (
                f"Got wrong sequence UUID: {sequence_uuid}"
            )
            assert upload_result.error is None, (
                f"Upload failed with error: {upload_result.error}"
            )
            assert upload_result.result is not None, "Upload should return a cluster ID"

            # Test that cache operations are safely ignored when cache is disabled
            # These operations should not throw errors even when cache is None
            test_key = "test_no_cache_key"
            test_value = "test_no_cache_value"

            # Should safely return None without error
            retrieved_value = (
                sequence_uploader.single_image_uploader._get_cached_file_handle(
                    test_key
                )
            )
            assert retrieved_value is None, (
                "Cache get should return None when cache is disabled"
            )

            # Should safely do nothing without error
            sequence_uploader.single_image_uploader._set_file_handle_cache(
                test_key, test_value
            )

            # Verify the value is still None after attempted set
            retrieved_value_after_set = (
                sequence_uploader.single_image_uploader._get_cached_file_handle(
                    test_key
                )
            )
            assert retrieved_value_after_set is None, (
                "Cache should remain disabled after set attempt"
            )

    def test_image_sequence_uploader_cache_hits_second_run(
        self, setup_unittest_data: py.path.local
    ):
        """Test that cache hits work correctly for the second run when cache is enabled."""
        # Create upload options that enable cache
        upload_options_with_cache = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            dry_run=False,  # Cache requires dry_run=False initially
            noresume=False,  # Ensure we use md5-based session keys for caching
        )

        # Create a shared single image uploader to simulate cached behavior
        single_uploader = uploader.SingleImageUploader(upload_options_with_cache)
        assert single_uploader.cache is not None, "Cache should be enabled"

        # Override to dry_run=True for actual testing
        single_uploader.upload_options = dataclasses.replace(
            upload_options_with_cache, dry_run=True, noresume=False
        )

        test_exif = setup_unittest_data.join("test_exif.jpg")

        # Use the exact same image metadata for both uploads to test caching
        image_metadata = description.DescriptionJSONSerializer.from_desc(
            {
                "MAPLatitude": 58.5927694,
                "MAPLongitude": 16.1840944,
                "MAPCaptureTime": "2021_02_13_13_24_41_140",
                "filename": str(test_exif),
                "md5sum": "cache_test_md5_identical",
                "filetype": "image",
                "MAPSequenceUUID": "cache_test_sequence",
            }
        )

        # First upload - should populate cache
        with api_v4.create_user_session(
            upload_options_with_cache.user_items["user_upload_token"]
        ) as user_session:
            image_progress_1: dict = {}
            file_handle_1 = single_uploader.upload(
                user_session, image_metadata, image_progress_1
            )

        assert file_handle_1 is not None, "First upload should succeed"

        # Test direct cache access using exposed cache instance
        # Let's manually verify what's in the cache after first upload
        session_key_prefix = "test_cache_verification_"
        test_cache_key = f"{session_key_prefix}first_upload"
        test_cache_value = f"file_handle_from_first_upload_{file_handle_1}"

        # Direct cache set/get test
        single_uploader.cache.set(test_cache_key, test_cache_value)
        retrieved_direct = single_uploader.cache.get(test_cache_key)
        assert retrieved_direct == test_cache_value, (
            f"Direct cache access failed. Expected: {test_cache_value}, Got: {retrieved_direct}"
        )

        # Mock the cache to verify it's being used correctly during upload
        with (
            patch.object(single_uploader.cache, "get") as mock_cache_get,
            patch.object(single_uploader.cache, "set") as mock_cache_set,
        ):
            # Set up the mock to return the cached file handle
            mock_cache_get.return_value = file_handle_1

            # Second upload - should hit cache
            with api_v4.create_user_session(
                upload_options_with_cache.user_items["user_upload_token"]
            ) as user_session:
                image_progress_2: dict = {}
                file_handle_2 = single_uploader.upload(
                    user_session, image_metadata, image_progress_2
                )

            # Verify results are identical (from cache)
            assert file_handle_2 == file_handle_1, (
                f"Cached upload should return same handle. Expected: {file_handle_1}, Got: {file_handle_2}"
            )

            # Verify that cache.get() was called (indicating cache lookup happened)
            assert mock_cache_get.called, (
                "Cache get should have been called during second upload"
            )

            # Verify that cache.set() was NOT called during second upload (since it was a cache hit)
            # Note: mock_cache_set might have been called during first upload, but we only care about the second one
            # So we reset the mock and then check
            mock_cache_set.reset_mock()

            # Third upload with same metadata - should definitely hit cache and not call set
            with api_v4.create_user_session(
                upload_options_with_cache.user_items["user_upload_token"]
            ) as user_session:
                image_progress_3: dict = {}
                file_handle_3 = single_uploader.upload(
                    user_session, image_metadata, image_progress_3
                )

            assert file_handle_3 == file_handle_1, (
                "Third upload should also return cached handle"
            )
            assert not mock_cache_set.called, (
                "Cache set should NOT be called when cache hit occurs"
            )

        # Test cache manipulation through the exposed cache instance
        cache_manipulation_keys = []
        for i in range(5):
            key = f"test_cache_manipulation_{i}"
            value = f"test_value_{i}"

            # Set via exposed cache
            single_uploader.cache.set(key, value)
            cache_manipulation_keys.append((key, value))

            # Verify immediately via cache instance
            retrieved = single_uploader.cache.get(key)
            assert retrieved == value, f"Cache manipulation test {i} failed"

        # Verify all cache manipulation keys are still accessible
        for key, expected_value in cache_manipulation_keys:
            actual_value = single_uploader.cache.get(key)
            assert actual_value == expected_value, (
                f"Cache persistence failed for {key}. Expected: {expected_value}, Got: {actual_value}"
            )

        # Test manual cache operations for verification
        test_cache_key = "test_manual_cache_key_12345"
        test_cache_value = "test_file_handle_67890"

        # Set cache manually using the exposed cache instance
        single_uploader.cache.set(test_cache_key, test_cache_value)

        # Get cache manually via different method
        retrieved_value = single_uploader._get_cached_file_handle(test_cache_key)
        assert retrieved_value == test_cache_value, (
            f"Manual cache test failed. Expected: {test_cache_value}, Got: {retrieved_value}"
        )

        # Test cache sharing between different uploader instances using same cache
        another_uploader = uploader.SingleImageUploader(
            upload_options_with_cache, cache=single_uploader.cache
        )
        assert another_uploader.cache is single_uploader.cache, (
            "Cache instances should be shared"
        )

        # Set via first uploader, get via second
        shared_key = "test_shared_cache_key"
        shared_value = "test_shared_cache_value"
        single_uploader.cache.set(shared_key, shared_value)

        assert another_uploader.cache is not None, (
            "Another uploader cache should not be None"
        )
        retrieved_via_another = another_uploader.cache.get(shared_key)
        assert retrieved_via_another == shared_value, (
            f"Cache sharing between uploader instances failed. Expected: {shared_value}, Got: {retrieved_via_another}"
        )

    def test_image_sequence_uploader_cache_runtime_manipulation(
        self, setup_unittest_data: py.path.local
    ):
        """Test runtime cache manipulation through exposed cache instances."""
        # Create upload options that enable cache
        upload_options_with_cache = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            dry_run=False,  # Cache requires dry_run=False initially
        )
        emitter = uploader.EventEmitter()
        sequence_uploader = uploader.ImageSequenceUploader(
            upload_options_with_cache, emitter
        )

        # Override to dry_run=True for actual testing
        sequence_uploader.upload_options = dataclasses.replace(
            upload_options_with_cache, dry_run=True
        )

        # Verify initial cache state
        assert sequence_uploader.cache is not None, (
            "ImageSequenceUploader should have cache"
        )
        assert (
            sequence_uploader.single_image_uploader.cache is sequence_uploader.cache
        ), "Cache should be shared between sequence and single image uploaders"

        # Test 1: Pre-populate cache with custom data
        test_entries = [
            ("custom_key_1", "custom_value_1"),
            ("custom_key_2", "custom_value_2"),
            ("session_key_abc123", "file_handle_xyz789"),
        ]

        for key, value in test_entries:
            sequence_uploader.cache.set(key, value)

        # Verify all entries were set correctly
        for key, expected_value in test_entries:
            actual_value = sequence_uploader.cache.get(key)
            assert actual_value == expected_value, (
                f"Cache set/get failed for {key}. Expected: {expected_value}, Got: {actual_value}"
            )

        # Test 2: Verify cache is accessible from SingleImageUploader
        for key, expected_value in test_entries:
            assert sequence_uploader.single_image_uploader.cache is not None, (
                "SingleImageUploader cache should not be None"
            )
            actual_value = sequence_uploader.single_image_uploader.cache.get(key)
            assert actual_value == expected_value, (
                f"Cache access via SingleImageUploader failed for {key}. Expected: {expected_value}, Got: {actual_value}"
            )

        # Test 3: Runtime cache replacement
        # Create a new cache instance and replace the existing one
        original_cache = sequence_uploader.cache

        # Simulate creating a new cache instance (this would be for testing cache switching)
        # Use a different user token to ensure a different cache instance
        upload_options_for_new_cache = uploader.UploadOptions(
            {
                "user_upload_token": "DIFFERENT_USER_ACCESS_TOKEN"
            },  # Different user token for different cache
            dry_run=False,  # Enable cache creation
        )

        # Create a new SingleImageUploader with its own cache
        temp_uploader = uploader.SingleImageUploader(upload_options_for_new_cache)
        new_cache = temp_uploader.cache
        assert new_cache is not None, "New cache should be created"
        # Note: new_cache might use the same cache file if using same user token, so we check identity instead
        # This is actually expected behavior - caches for the same user should share data

        # Replace the cache in the sequence uploader
        sequence_uploader.cache = new_cache
        sequence_uploader.single_image_uploader.cache = new_cache

        # Verify the cache was replaced
        assert sequence_uploader.cache is new_cache, "Cache replacement failed"
        assert sequence_uploader.single_image_uploader.cache is new_cache, (
            "SingleImageUploader cache replacement failed"
        )

        # Test if the caches are truly isolated (they may not be if using same storage backend)
        cache_isolation_test_key = "cache_isolation_test"
        cache_isolation_test_value = "value_in_new_cache"

        # Set in new cache
        sequence_uploader.cache.set(
            cache_isolation_test_key, cache_isolation_test_value
        )

        # Check if it appears in original cache (it might, and that's OK for same user)
        value_in_original = original_cache.get(cache_isolation_test_key)

        if value_in_original is None:
            # Caches are truly isolated
            print("Cache instances are isolated")
        else:
            # Caches share the same backend (expected for same user scenarios)
            print("Cache instances share the same backend (expected)")
            assert value_in_original == cache_isolation_test_value, (
                "Shared cache should have consistent data"
            )

        # Test 4: Populate new cache and verify functionality
        new_test_entries = [
            ("new_cache_key_1", "new_cache_value_1"),
            ("new_cache_key_2", "new_cache_value_2"),
        ]

        for key, value in new_test_entries:
            sequence_uploader.cache.set(key, value)

        # Verify new entries in new cache
        for key, expected_value in new_test_entries:
            actual_value = sequence_uploader.cache.get(key)
            assert actual_value == expected_value, (
                f"New cache set/get failed for {key}. Expected: {expected_value}, Got: {actual_value}"
            )

        # Verify original cache still functions independently (if they're truly different instances)
        original_test_key = "original_cache_test"
        original_test_value = "original_cache_value"

        # Only test original cache isolation if it's a different object
        if original_cache is not sequence_uploader.cache:
            original_cache.set(original_test_key, original_test_value)

            # This key should not appear in the new cache
            value_in_new_cache = sequence_uploader.cache.get(original_test_key)
            assert value_in_new_cache is None, (
                f"Original cache key should not appear in new cache: {original_test_key}"
            )

            # But should be in original cache
            value_in_original = original_cache.get(original_test_key)
            assert value_in_original == original_test_value, (
                "Original cache should have its own entries"
            )

        # Test 5: Cache instance sharing verification
        # Create another sequence uploader with the same cache
        another_sequence_uploader = uploader.ImageSequenceUploader(
            upload_options_with_cache, emitter
        )
        another_sequence_uploader.cache = new_cache
        another_sequence_uploader.single_image_uploader.cache = new_cache

        # Set via one uploader, get via another
        shared_test_key = "shared_between_uploaders"
        shared_test_value = "shared_test_value"

        sequence_uploader.cache.set(shared_test_key, shared_test_value)
        retrieved_via_another = another_sequence_uploader.cache.get(shared_test_key)

        assert retrieved_via_another == shared_test_value, (
            f"Cache sharing between sequence uploaders failed. Expected: {shared_test_value}, Got: {retrieved_via_another}"
        )

        # Test 6: Cache clearing behavior (if supported)
        try:
            # Some cache implementations might support clearing
            cache_clear_key = "cache_clear_test"
            cache_clear_value = "cache_clear_value"

            sequence_uploader.cache.set(cache_clear_key, cache_clear_value)
            assert sequence_uploader.cache.get(cache_clear_key) == cache_clear_value

            # Clear expired entries (this is a method we know exists)
            cleared_keys = sequence_uploader.cache.clear_expired()
            # cleared_keys should be a list of cleared keys
            assert isinstance(cleared_keys, list), "clear_expired should return a list"

        except (AttributeError, NotImplementedError):
            # Cache might not support all operations
            pass

    def test_image_sequence_uploader_multiple_sequences(
        self, setup_unittest_data: py.path.local
    ):
        """Test ImageSequenceUploader with multiple sequences."""
        upload_options = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            dry_run=True,
        )
        emitter = uploader.EventEmitter()
        sequence_uploader = uploader.ImageSequenceUploader(upload_options, emitter)

        test_exif = setup_unittest_data.join("test_exif.jpg")
        fixed_exif = setup_unittest_data.join("fixed_exif.jpg")

        # Create metadata for multiple sequences
        image_metadatas = [
            # Sequence 1 - 2 images
            description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927694,
                    "MAPLongitude": 16.1840944,
                    "MAPCaptureTime": "2021_02_13_13_24_41_140",
                    "filename": str(test_exif),
                    "md5sum": "multi_seq_md5_1_1",
                    "filetype": "image",
                    "MAPSequenceUUID": "multi_sequence_1",
                }
            ),
            description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927695,
                    "MAPLongitude": 16.1840945,
                    "MAPCaptureTime": "2021_02_13_13_24_42_140",
                    "filename": str(test_exif),
                    "md5sum": "multi_seq_md5_1_2",
                    "filetype": "image",
                    "MAPSequenceUUID": "multi_sequence_1",
                }
            ),
            # Sequence 2 - 1 image
            description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 59.5927694,
                    "MAPLongitude": 17.1840944,
                    "MAPCaptureTime": "2021_02_13_13_25_41_140",
                    "filename": str(fixed_exif),
                    "md5sum": "multi_seq_md5_2_1",
                    "filetype": "image",
                    "MAPSequenceUUID": "multi_sequence_2",
                }
            ),
        ]

        # Test upload
        results = list(sequence_uploader.upload_images(image_metadatas))

        assert len(results) == 2, f"Expected 2 sequences, got {len(results)}"

        # Verify both sequences uploaded successfully
        sequence_results = {seq_uuid: result for seq_uuid, result in results}

        assert "multi_sequence_1" in sequence_results, "Sequence 1 should be present"
        assert "multi_sequence_2" in sequence_results, "Sequence 2 should be present"

        result_1 = sequence_results["multi_sequence_1"]
        result_2 = sequence_results["multi_sequence_2"]

        assert result_1.error is None, (
            f"Sequence 1 should not have error: {result_1.error}"
        )
        assert result_1.result is not None, "Sequence 1 should have result"

        assert result_2.error is None, (
            f"Sequence 2 should not have error: {result_2.error}"
        )
        assert result_2.result is not None, "Sequence 2 should have result"

    def test_image_sequence_uploader_event_emission(
        self, setup_unittest_data: py.path.local
    ):
        """Test that ImageSequenceUploader properly emits events during upload."""
        upload_options = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            dry_run=True,
        )
        emitter = uploader.EventEmitter()
        sequence_uploader = uploader.ImageSequenceUploader(upload_options, emitter)

        # Track emitted events
        emitted_events = []

        @emitter.on("upload_start")
        def on_upload_start(payload):
            emitted_events.append(("upload_start", payload.copy()))

        @emitter.on("upload_end")
        def on_upload_end(payload):
            emitted_events.append(("upload_end", payload.copy()))

        @emitter.on("upload_finished")
        def on_upload_finished(payload):
            emitted_events.append(("upload_finished", payload.copy()))

        test_exif = setup_unittest_data.join("test_exif.jpg")
        image_metadatas = [
            description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927694,
                    "MAPLongitude": 16.1840944,
                    "MAPCaptureTime": "2021_02_13_13_24_41_140",
                    "filename": str(test_exif),
                    "md5sum": "event_test_md5_1",
                    "filetype": "image",
                    "MAPSequenceUUID": "event_test_sequence",
                }
            ),
        ]

        # Test upload
        results = list(sequence_uploader.upload_images(image_metadatas))

        assert len(results) == 1
        sequence_uuid, upload_result = results[0]
        assert upload_result.error is None

        # Verify events were emitted
        assert len(emitted_events) >= 3, (
            f"Expected at least 3 events, got {len(emitted_events)}"
        )

        event_types = [event[0] for event in emitted_events]
        assert "upload_start" in event_types, "upload_start event should be emitted"
        assert "upload_end" in event_types, "upload_end event should be emitted"
        assert "upload_finished" in event_types, (
            "upload_finished event should be emitted"
        )

        # Verify event payload structure
        start_event = next(
            event for event in emitted_events if event[0] == "upload_start"
        )
        start_payload = start_event[1]

        assert "sequence_uuid" in start_payload, (
            "upload_start should contain sequence_uuid"
        )
        assert "entity_size" in start_payload, "upload_start should contain entity_size"
        assert start_payload["sequence_uuid"] == "event_test_sequence"
