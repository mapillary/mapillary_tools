# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import dataclasses
import typing as T
from pathlib import Path
from unittest.mock import patch

import py.path
import pytest
from mapillary_tools import api_v4, geo, types, upload, uploader
from mapillary_tools.mp4 import construct_mp4_parser as cparser
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
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            dry_run=True,
            upload_cache_path=Path(setup_unittest_data.join("upload_cache")),
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
            upload_cache_path=Path(setup_unittest_data.join("upload_cache")),
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
            upload_cache_path=Path(setup_unittest_data.join("upload_cache")),
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


def _write_empty_mp4(path: Path, timescale: int) -> None:
    mvhd: cparser.BoxDict = {
        "type": b"mvhd",
        "data": {
            "creation_time": 0,
            "modification_time": 0,
            "timescale": timescale,
            "duration": 10 * timescale,
        },
    }
    path.write_bytes(
        cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist(
            [{"type": b"ftyp", "data": b"test"}, {"type": b"moov", "data": [mvhd]}]
        )
    )


def test_upload_continues_after_points_too_far_apart(
    tmpdir: py.path.local, setup_upload: py.path.local, caplog
):
    video_dir = Path(tmpdir.mkdir("videos"))
    metadatas = []
    # 79740 s is 4784400000 ticks of 1/60000 s, more than 32 bits can hold
    for name, last_time in [("a_bad.mp4", 79740.0), ("b_good.mp4", 1.0)]:
        _write_empty_mp4(video_dir / name, 60000)
        metadatas.append(
            types.VideoMetadata(
                video_dir / name,
                types.FileType.VIDEO,
                points=[
                    geo.Point(time=0.0, lat=1, lon=1, alt=None, angle=None),
                    geo.Point(time=last_time, lat=1.0001, lon=1, alt=None, angle=None),
                ],
            )
        )

    results = {
        metadata.filename.name: result
        for metadata, result in uploader.VideoUploader.upload_videos(
            uploader.Uploader(
                uploader.UploadOptions(
                    {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"}, dry_run=True
                )
            ),
            metadatas,
        )
    }
    assert isinstance(results["a_bad.mp4"].error, uploader.GPSPointsTooFarApartError)
    assert "a_bad.mp4: Points at 0.000 s and 79740.000 s of the video" in str(
        results["a_bad.mp4"].error
    )
    assert results["b_good.mp4"].error is None
    assert results["b_good.mp4"].result == "0"

    # The whole upload goes on to the next video instead of stopping
    upload.upload(
        video_dir,
        {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
        num_upload_workers=1,
        _metadatas_from_process=metadatas,
        reupload=True,
        dry_run=True,
    )
    assert "GPSPointsTooFarApartError: a_bad.mp4" in caplog.text


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


class TestImageSequenceUploader:
    """Test suite for ImageSequenceUploader with focus on multithreading scenarios and caching."""

    def test_image_sequence_uploader_basic(self, setup_unittest_data: py.path.local):
        """Test basic functionality of ImageSequenceUploader."""
        upload_options = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            upload_cache_path=Path(setup_unittest_data.join("upload_cache")),
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
            upload_cache_path=Path(setup_unittest_data.join("upload_cache")),
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
        sequence_uploader.cached_image_uploader.upload_options = dataclasses.replace(
            upload_options_with_cache, dry_run=True
        )

        # Verify cache is available and shared
        assert sequence_uploader.cached_image_uploader.cache is not None, (
            "SingleImageUploader should share the same cache instance"
        )

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
                upload_cache_path=Path(setup_unittest_data.join("upload_cache")),
                num_upload_workers=4,  # This will be used internally for parallel image uploads
                dry_run=True,
            )
            emitter = uploader.EventEmitter()
            sequence_uploader = uploader.ImageSequenceUploader(upload_options, emitter)

            # Verify cache is disabled for both instances
            assert sequence_uploader.cached_image_uploader.cache is None, (
                "Should have cache disabled"
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
                sequence_uploader.cached_image_uploader._get_cached_file_handle(
                    test_key
                )
            )
            assert retrieved_value is None, (
                "Cache get should return None when cache is disabled"
            )

            # Should safely do nothing without error
            sequence_uploader.cached_image_uploader._set_file_handle_cache(
                test_key, test_value
            )

            # Verify the value is still None after attempted set
            retrieved_value_after_set = (
                sequence_uploader.cached_image_uploader._get_cached_file_handle(
                    test_key
                )
            )
            assert retrieved_value_after_set is None, (
                "Cache should remain disabled after set attempt"
            )

    def test_image_sequence_uploader_cache_hits_second_run(
        self, setup_unittest_data: py.path.local
    ):
        """Test that cache hits work correctly for ImageSequenceUploader with overlapping uploads."""
        # Create upload options that enable cache but use dry_run for testing
        # We need to create the cache instance separately to avoid the dry_run check

        # Create cache-enabled options to initialize the cache
        cache_enabled_options = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            upload_cache_path=Path(setup_unittest_data.join("upload_cache")),
            dry_run=False,  # Cache requires dry_run=False initially
        )

        # Create the sequence uploader - your changes now automatically expose cache
        emitter = uploader.EventEmitter()
        sequence_uploader = uploader.ImageSequenceUploader(
            cache_enabled_options, emitter
        )

        # Override to dry_run=True for actual testing (cache remains intact)
        sequence_uploader.upload_options = dataclasses.replace(
            cache_enabled_options, dry_run=True
        )
        sequence_uploader.cached_image_uploader.upload_options = dataclasses.replace(
            cache_enabled_options, dry_run=True
        )

        # 1. Make sure cache is enabled
        assert sequence_uploader.cached_image_uploader.cache is not None, (
            "Cache should be enabled"
        )

        test_exif = setup_unittest_data.join("test_exif.jpg")
        test_exif1 = setup_unittest_data.join("test_exif_1.jpg")
        test_exif.copy(test_exif1)
        test_exif2 = setup_unittest_data.join("test_exif_2.jpg")
        test_exif.copy(test_exif2)
        test_exif3 = setup_unittest_data.join("test_exif_3.jpg")
        test_exif.copy(test_exif3)
        test_exif4 = setup_unittest_data.join("test_exif_4.jpg")
        test_exif.copy(test_exif4)
        test_exif5 = setup_unittest_data.join("test_exif_5.jpg")
        test_exif.copy(test_exif5)

        # Create simpler test data to focus on cache behavior
        # Create image metadata for images a, b, c, d, e
        images = {
            "a": description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927694,
                    "MAPLongitude": 16.1840944,
                    "MAPCaptureTime": "2021_02_13_13_24_41_140",
                    "filename": str(test_exif1),
                    "filetype": "image",
                    "MAPSequenceUUID": "cache_test_sequence_1",
                }
            ),
            "b": description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927695,
                    "MAPLongitude": 16.1840945,
                    "MAPCaptureTime": "2021_02_13_13_24_42_141",
                    "filename": str(test_exif2),
                    "filetype": "image",
                    "MAPSequenceUUID": "cache_test_sequence_1",
                }
            ),
            "c": description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927696,
                    "MAPLongitude": 16.1840946,
                    "MAPCaptureTime": "2021_02_13_13_24_43_142",
                    "filename": str(test_exif3),
                    "filetype": "image",
                    "MAPSequenceUUID": "cache_test_sequence_1",
                }
            ),
            "d": description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927697,
                    "MAPLongitude": 16.1840947,
                    "MAPCaptureTime": "2021_02_13_13_24_44_143",
                    "filename": str(test_exif4),
                    "filetype": "image",
                    "MAPSequenceUUID": "cache_test_sequence_2",
                }
            ),
            "e": description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927698,
                    "MAPLongitude": 16.1840948,
                    "MAPCaptureTime": "2021_02_13_13_24_45_144",
                    "filename": str(test_exif5),
                    "filetype": "image",
                    "MAPSequenceUUID": "cache_test_sequence_2",
                }
            ),
        }

        assert list(sequence_uploader.cached_image_uploader.cache.keys()) == []
        results_1 = list(
            sequence_uploader.upload_images([images["a"], images["b"], images["c"]])
        )

        # Assert that first upload has no errors
        assert len(results_1) == 1
        sequence_uuid_1, upload_result_1 = results_1[0]
        assert upload_result_1.error is None, (
            f"First upload failed with error: {upload_result_1.error}"
        )
        assert upload_result_1.result is not None

        # Capture cache keys after first upload
        first_upload_cache_keys = set(
            sequence_uploader.cached_image_uploader.cache.keys()
        )
        assert len(first_upload_cache_keys) == 3

        results_2 = list(
            sequence_uploader.upload_images(
                [
                    images["c"],  # Should hit cache
                    images["d"],  # New image, should upload
                    images["e"],  # New image, should upload
                ]
            )
        )

        # Assert that second upload has no errors
        assert (
            len(results_2) == 2
        )  # Two sequences: cache_test_sequence_1 and cache_test_sequence_2
        for sequence_uuid, upload_result in results_2:
            assert upload_result.error is None, (
                f"Second upload failed with error: {upload_result.error}"
            )
            assert upload_result.result is not None

        # Capture cache keys after second upload
        second_upload_cache_keys = set(
            sequence_uploader.cached_image_uploader.cache.keys()
        )
        assert len(second_upload_cache_keys) == 5

        # Assert that all keys from first upload are still present in second upload
        assert first_upload_cache_keys.issubset(second_upload_cache_keys), (
            f"Cache keys from first upload {first_upload_cache_keys} should be "
            f"contained in second upload cache keys {second_upload_cache_keys}"
        )

    def test_image_sequence_uploader_multiple_sequences(
        self, setup_unittest_data: py.path.local
    ):
        """Test ImageSequenceUploader with multiple sequences."""
        upload_options = uploader.UploadOptions(
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            upload_cache_path=Path(setup_unittest_data.join("upload_cache")),
            dry_run=True,
        )
        emitter = uploader.EventEmitter()
        sequence_uploader = uploader.ImageSequenceUploader(upload_options, emitter)

        test_exif = setup_unittest_data.join("test_exif.jpg")
        test_exif1 = setup_unittest_data.join("test_exif_1.jpg")
        test_exif.copy(test_exif1)
        test_exif2 = setup_unittest_data.join("test_exif_2.jpg")
        test_exif.copy(test_exif2)
        test_exif3 = setup_unittest_data.join("test_exif_3.jpg")
        test_exif.copy(test_exif3)

        # Create metadata for multiple sequences
        image_metadatas = [
            # Sequence 1 - 2 images
            description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927694,
                    "MAPLongitude": 16.1840944,
                    "MAPCaptureTime": "2021_02_13_13_24_41_140",
                    "filename": str(test_exif1),
                    "filetype": "image",
                    "MAPSequenceUUID": "multi_sequence_1",
                }
            ),
            description.DescriptionJSONSerializer.from_desc(
                {
                    "MAPLatitude": 58.5927695,
                    "MAPLongitude": 16.1840945,
                    "MAPCaptureTime": "2021_02_13_13_24_42_140",
                    "filename": str(test_exif2),
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
                    "filename": str(test_exif3),
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
            upload_cache_path=Path(setup_unittest_data.join("upload_cache")),
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
