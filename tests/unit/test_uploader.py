import typing as T
from pathlib import Path
import dataclasses
import concurrent.futures
import time
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
                single_uploader._get_cached_file_handle(cache_key)

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
        upload_options = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            num_upload_workers=4,  # This will be used internally for parallel image uploads
            dry_run=True,
        )
        emitter = uploader.EventEmitter()
        sequence_uploader = uploader.ImageSequenceUploader(upload_options, emitter)

        test_exif = setup_unittest_data.join("test_exif.jpg")

        # Create a larger sequence with multiple images to test internal multithreading
        # This will trigger the internal _upload_images_parallel method with multiple workers
        num_images = 12  # More than num_upload_workers to test parallel processing
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

            test_exif = setup_unittest_data.join("test_exif.jpg")

            # Create a larger sequence with multiple images to test internal multithreading
            # This will trigger the internal _upload_images_parallel method with multiple workers
            num_images = 10  # More than num_upload_workers to test parallel processing
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

        # Second upload - should hit cache and be faster
        start_time = time.time()

        with api_v4.create_user_session(
            upload_options_with_cache.user_items["user_upload_token"]
        ) as user_session:
            image_progress_2: dict = {}
            file_handle_2 = single_uploader.upload(
                user_session, image_metadata, image_progress_2
            )

        cached_time = time.time() - start_time

        # Verify results are identical (from cache)
        assert file_handle_2 == file_handle_1, (
            f"Cached upload should return same handle. Expected: {file_handle_1}, Got: {file_handle_2}"
        )

        # Cached uploads should be significantly faster (less than 0.5 second)
        assert cached_time < 0.5, (
            f"Cached upload took too long: {cached_time}s, should be much faster due to cache hit"
        )

        # Test manual cache operations for verification
        # Use a known test key for direct cache testing
        test_cache_key = "test_manual_cache_key_12345"
        test_cache_value = "test_file_handle_67890"

        # Set cache manually
        single_uploader._set_file_handle_cache(test_cache_key, test_cache_value)

        # Get cache manually
        retrieved_value = single_uploader._get_cached_file_handle(test_cache_key)

        assert retrieved_value == test_cache_value, (
            f"Manual cache test failed. Expected: {test_cache_value}, Got: {retrieved_value}"
        )

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
