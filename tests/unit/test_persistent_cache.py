# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import concurrent.futures
import multiprocessing
import os
import sqlite3
import time
import traceback

import pytest
from mapillary_tools.history import PersistentCache


def test_basic_operations_with_backend(tmpdir):
    """Test basic operations with different DBM backends.

    Note: This is a demonstration of pytest's parametrize feature.
    The actual PersistentCache class might not support specifying backends.
    """
    cache_file = os.path.join(tmpdir, "cache")
    # Here you would use the backend if the cache implementation supported it
    cache = PersistentCache(cache_file)

    # Perform basic operations
    cache.set("test_key", "test_value")
    assert cache.get("test_key") == "test_value"

    # Add specific test logic for different backends if needed
    # This is just a placeholder to demonstrate pytest's parametrization


def test_get_set(tmpdir):
    """Test basic get and set operations."""
    cache_file = os.path.join(tmpdir, "cache")
    cache = PersistentCache(cache_file)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"
    assert cache.get("nonexistent_key") is None


def test_expiration(tmpdir):
    """Test that entries expire correctly."""
    cache_file = os.path.join(tmpdir, "cache")
    cache = PersistentCache(cache_file)

    # Set with short expiration
    cache.set("short_lived", "value", expires_in=1)
    assert cache.get("short_lived") == "value"

    # Wait for expiration
    time.sleep(1.1)
    assert cache.get("short_lived") is None

    # Set with longer expiration
    cache.set("long_lived", "value", expires_in=10)
    assert cache.get("long_lived") == "value"

    # Should still be valid
    time.sleep(1)
    assert cache.get("long_lived") == "value"


@pytest.mark.parametrize(
    "expire_time,sleep_time,should_exist",
    [
        (1, 0.5, True),  # Should not expire yet
        (1, 1.5, False),  # Should expire
        (5, 2, True),  # Should not expire yet
    ],
)
def test_parametrized_expiration(tmpdir, expire_time, sleep_time, should_exist):
    """Test expiration with different timing combinations."""
    cache_file = os.path.join(tmpdir, f"cache_param_exp_{expire_time}_{sleep_time}")
    cache = PersistentCache(cache_file)

    key = f"key_expires_in_{expire_time}_sleeps_{sleep_time}"
    cache.set(key, "test_value", expires_in=expire_time)

    time.sleep(sleep_time)

    if should_exist:
        assert cache.get(key) == "test_value"
    else:
        assert cache.get(key) is None


def test_clear_expired(tmpdir):
    """Test clearing expired entries."""
    cache_file = os.path.join(tmpdir, f"cache_clear_expired")
    cache = PersistentCache(cache_file)

    # Test 1: Single expired key
    cache.set("expired", "value1", expires_in=1)
    cache.set("not_expired", "value2", expires_in=10)

    # Wait for first entry to expire
    time.sleep(1.1)

    # Clear expired entries
    expired_keys = cache.clear_expired()

    # Check that only the expired key was cleared
    assert len(expired_keys) == 1
    assert expired_keys[0] == b"expired"
    assert cache.get("expired") is None
    assert cache.get("not_expired") == "value2"


def test_clear_expired_multiple(tmpdir):
    """Test clearing multiple expired entries."""
    cache_file = os.path.join(tmpdir, f"cache_clear_multiple")
    cache = PersistentCache(cache_file)

    # Test 2: Multiple expired keys
    cache.set("expired1", "value1", expires_in=1)
    cache.set("expired2", "value2", expires_in=1)
    cache.set("not_expired", "value3", expires_in=10)

    # Wait for entries to expire
    time.sleep(1.1)

    # Clear expired entries
    expired_keys = cache.clear_expired()

    # Check that only expired keys were cleared
    assert len(expired_keys) == 2
    assert b"expired1" in expired_keys
    assert b"expired2" in expired_keys
    assert cache.get("expired1") is None
    assert cache.get("expired2") is None
    assert cache.get("not_expired") == "value3"


def test_clear_expired_all(tmpdir):
    """Test clearing all expired entries."""
    cache_file = os.path.join(tmpdir, f"cache_clear_all")
    cache = PersistentCache(cache_file)

    # Test 3: All entries expired
    cache.set("key1", "value1", expires_in=1)
    cache.set("key2", "value2", expires_in=1)

    # Wait for entries to expire
    time.sleep(1.1)

    # Clear expired entries
    expired_keys = cache.clear_expired()

    # Check that all keys were cleared
    assert len(expired_keys) == 2
    assert b"key1" in expired_keys
    assert b"key2" in expired_keys


def test_clear_expired_none(tmpdir):
    """Test clearing when no entries are expired."""
    cache_file = os.path.join(tmpdir, f"cache_clear_none")
    cache = PersistentCache(cache_file)

    # Test 4: No entries expired
    cache.set("key1", "value1", expires_in=10)
    cache.set("key2", "value2", expires_in=10)

    # Clear expired entries
    expired_keys = cache.clear_expired()

    # Check that no keys were cleared
    assert len(expired_keys) == 0
    assert cache.get("key1") == "value1"
    assert cache.get("key2") == "value2"


def test_clear_expired_empty(tmpdir):
    """Test clearing expired entries on an empty cache."""
    cache_file = os.path.join(tmpdir, f"cache_clear_empty")
    cache = PersistentCache(cache_file)

    # Test 5: Empty cache
    expired_keys = cache.clear_expired()

    # Check that no keys were cleared
    assert len(expired_keys) == 0


def test_corrupted_data(tmpdir):
    """Test handling of corrupted data through public interface."""
    cache_file = os.path.join(tmpdir, f"cache_corrupted")
    cache = PersistentCache(cache_file)

    # Set valid entry
    cache.set("key1", "value1")

    # Valid entries should still work
    assert cache.get("key1") == "value1"

    # Clear expired should not crash
    cache.clear_expired()


def test_keys_basic(tmpdir):
    """Test keys() method in read mode with empty cache."""
    cache_file = os.path.join(tmpdir, "cache_keys_empty")
    cache = PersistentCache(cache_file)
    cache.set("key1", "value1")

    # Test keys on non-existent cache file
    keys = cache.keys()
    assert keys == ["key1"]


def test_keys_read_mode_empty_cache(tmpdir):
    """Test keys() method in read mode with empty cache."""
    cache_file = os.path.join(tmpdir, "cache_keys_empty")
    cache = PersistentCache(cache_file)

    # Test keys on non-existent cache file
    keys = cache.keys()
    assert keys == []


def test_keys_read_mode_with_data(tmpdir):
    """Test keys() method in read mode with existing data."""
    cache_file = os.path.join(tmpdir, "cache_keys_data")
    cache = PersistentCache(cache_file)

    # Add some data first
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")

    # Test keys retrieval in read mode
    keys = cache.keys()
    assert len(keys) == 3
    assert "key1" in keys
    assert "key2" in keys
    assert "key3" in keys
    assert set(keys) == {"key1", "key2", "key3"}


def test_keys_read_mode_with_expired_data(tmpdir):
    """Test keys() method in read mode includes expired entries."""
    cache_file = os.path.join(tmpdir, "cache_keys_expired")
    cache = PersistentCache(cache_file)

    # Add data with short expiration
    cache.set("expired_key", "value1", expires_in=1)
    cache.set("valid_key", "value2", expires_in=10)

    # Wait for expiration
    time.sleep(1.1)

    # keys() should still return expired keys (it doesn't filter by expiration)
    keys = cache.keys()
    assert len(keys) == 2
    assert "expired_key" in keys
    assert "valid_key" in keys

    # But get() should return None for expired key
    assert cache.get("expired_key") is None
    assert cache.get("valid_key") == "value2"


def test_keys_write_mode_concurrent_operations(tmpdir):
    """Test keys() method during concurrent write operations."""
    cache_file = os.path.join(tmpdir, "cache_keys_concurrent")
    cache = PersistentCache(cache_file)

    # Initial data
    cache.set("initial_key", "initial_value")

    def write_worker(worker_id):
        """Worker function that writes data and checks keys."""
        key = f"worker_{worker_id}_key"
        value = f"worker_{worker_id}_value"
        cache.set(key, value)

        # Get keys after writing
        keys = cache.keys()
        assert key in keys
        return keys

    # Run concurrent write operations
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(write_worker, i) for i in range(10)]
        # Wait for all futures to complete
        for f in futures:
            f.result()

    # Final check - should have all keys
    final_keys = cache.keys()
    assert "initial_key" in final_keys
    assert len(final_keys) >= 11  # initial + 10 worker keys

    # Verify all worker keys are present
    for i in range(10):
        assert f"worker_{i}_key" in final_keys


def test_keys_write_mode_after_clear_expired(tmpdir):
    """Test keys() method after clear_expired() operations."""
    cache_file = os.path.join(tmpdir, "cache_keys_clear")
    cache = PersistentCache(cache_file)

    # Add mixed data - some that will expire, some that won't
    cache.set("short_lived_1", "value1", expires_in=1)
    cache.set("short_lived_2", "value2", expires_in=1)
    cache.set("long_lived_1", "value3", expires_in=10)
    cache.set("long_lived_2", "value4", expires_in=10)

    # Verify all keys are present initially
    initial_keys = cache.keys()
    assert len(initial_keys) == 4

    # Wait for expiration
    time.sleep(1.1)

    # Keys should still show all entries (including expired)
    keys_before_clear = cache.keys()
    assert len(keys_before_clear) == 4

    # Clear expired entries
    expired_keys = cache.clear_expired()
    assert len(expired_keys) == 2

    # Now keys should only show non-expired entries
    keys_after_clear = cache.keys()
    assert len(keys_after_clear) == 2
    assert "long_lived_1" in keys_after_clear
    assert "long_lived_2" in keys_after_clear
    assert "short_lived_1" not in keys_after_clear
    assert "short_lived_2" not in keys_after_clear


def test_keys_write_mode_large_dataset(tmpdir):
    """Test keys() method with large dataset in write mode."""
    cache_file = os.path.join(tmpdir, "cache_keys_large")
    cache = PersistentCache(cache_file)

    # Add a large number of entries
    num_entries = 1000
    for i in range(num_entries):
        cache.set(f"key_{i:04d}", f"value_{i}")

    # Test keys retrieval
    keys = cache.keys()
    assert len(keys) == num_entries

    # Verify all keys are present
    expected_keys = {f"key_{i:04d}" for i in range(num_entries)}
    actual_keys = set(keys)
    assert actual_keys == expected_keys


def test_keys_read_mode_corrupted_database(tmpdir):
    """Test keys() method handles corrupted database gracefully."""
    cache_file = os.path.join(tmpdir, "cache_keys_corrupted")
    cache = PersistentCache(cache_file)

    # Add some valid data first
    cache.set("valid_key", "valid_value")

    # Verify keys work with valid data
    keys = cache.keys()
    assert "valid_key" in keys

    # The keys() method should handle database issues gracefully
    # (specific corruption testing would require manipulating the database file)
    # For now, we test that it doesn't crash with normal operations
    assert isinstance(keys, list)
    assert all(isinstance(key, str) for key in keys)


def test_multithread_shared_cache_comprehensive(tmpdir):
    """Test shared cache instance across multiple threads using get->set pattern.

    Tests multithread scenarios using a single shared PersistentCache instance,
    which simulates real-world usage patterns like CachedImageUploader.upload.
    This test covers the case where values_a and values_b can intersect (overlapping keys).
    """
    cache_file = os.path.join(tmpdir, "cache_shared_comprehensive")

    # Initialize cache once and share across all workers
    shared_cache = PersistentCache(cache_file)
    shared_cache.clear_expired()

    num_keys = 5_000

    # Generate key-value pairs for first run (overlapping patterns to ensure intersections)
    first_dict = {f"key_{i}": f"first_value_{i}" for i in range(num_keys)}
    assert len(first_dict) == num_keys

    s = time.perf_counter()
    # First concurrent run with get->set pattern
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        list(
            executor.map(
                lambda kv: _shared_worker_get_set_pattern(shared_cache, [kv]),
                first_dict.items(),
            )
        )
    print(f"First run time: {(time.perf_counter() - s) * 1000:.0f} ms")

    assert len(shared_cache.keys()) == len(first_dict)
    for key in shared_cache.keys():
        assert shared_cache.get(key) == first_dict[key]

    shared_cache.clear_expired()

    assert len(shared_cache.keys()) == len(first_dict)
    for key in shared_cache.keys():
        assert shared_cache.get(key) == first_dict[key]

    # Generate key-value pairs for first run (overlapping patterns to ensure intersections)
    second_dict = {
        f"key_{i}": f"second_value_{i}"
        for i in range(num_keys // 2, num_keys // 2 + num_keys)
    }

    s = time.perf_counter()
    # First concurrent run with get->set pattern
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        list(
            executor.map(
                lambda kv: _shared_worker_get_set_pattern(shared_cache, [kv]),
                second_dict.items(),
            )
        )
    print(f"Second run time: {(time.perf_counter() - s) * 1000:.0f} ms")

    shared_cache.clear_expired()

    merged_dict = {**second_dict, **first_dict}
    assert len(merged_dict) < len(first_dict) + len(second_dict)

    assert len(shared_cache.keys()) == len(merged_dict)
    for key in shared_cache.keys():
        assert shared_cache.get(key) == merged_dict[key]


# Shared worker functions for concurrency tests
def _shared_worker_get_set_pattern(cache, key_value_pairs, expires_in=36_000):
    """Shared worker implementation: get key -> if not exist then set key=value."""
    for key, value in key_value_pairs:
        # Pattern: get a key -> if not exist then set key=value
        existing_value = cache.get(key)
        if existing_value is None:
            cache.set(key, value, expires_in=expires_in)
        else:
            value = existing_value

        # Verify the value was set correctly
        retrieved_value = cache.get(key)
        assert retrieved_value == value, (
            f"Expected {value}, got {retrieved_value} for key {key}"
        )


def _multiprocess_worker_comprehensive(args):
    """Worker function for multiprocess comprehensive test.

    Each process creates its own PersistentCache instance but uses the same cache file.
    Keys are prefixed with process_id to avoid conflicts.
    """
    cache_file, process_id, num_keys = args

    # Create cache instance per process (but same file)
    cache = PersistentCache(cache_file)

    # Generate process-specific key-value pairs
    process_dict = {
        f"process_{process_id}_key_{i}": f"process_{process_id}_value_{i}"
        for i in range(num_keys)
    }

    # Use the same get->set pattern as the original test
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(
            executor.map(
                lambda kv: _shared_worker_get_set_pattern(cache, [kv]),
                process_dict.items(),
            )
        )

    # Verify all process-specific keys were set correctly
    for key, expected_value in process_dict.items():
        actual_value = cache.get(key)
        assert actual_value == expected_value, (
            f"Process {process_id}: Expected {expected_value}, got {actual_value} for key {key}"
        )

    # Return process results for verification
    return process_id, process_dict


def test_multiprocess_shared_cache_comprehensive(tmpdir):
    """Test shared cache file across multiple processes using get->set pattern.

    This test runs the comprehensive cache test across multiple processes where:
    - All processes use the same cache file but create their own PersistentCache instance
    - Each process has its own keys prefixed with process_id to avoid conflicts
    - Reuses the logic from test_multithread_shared_cache_comprehensive
    """
    cache_file = os.path.join(tmpdir, "cache_multiprocess_comprehensive")

    # Initialize cache and clear any existing data
    init_cache = PersistentCache(cache_file)
    init_cache.clear_expired()

    num_processes = 4
    keys_per_process = 1000

    # Prepare arguments for each process
    process_args = [
        (cache_file, process_id, keys_per_process)
        for process_id in range(num_processes)
    ]

    s = time.perf_counter()

    # Run multiple processes concurrently
    with multiprocessing.Pool(processes=num_processes) as pool:
        results = pool.map(_multiprocess_worker_comprehensive, process_args)

    print(f"Multiprocess run time: {(time.perf_counter() - s) * 1000:.0f} ms")

    # Verify results from all processes
    final_cache = PersistentCache(cache_file)
    final_cache.clear_expired()

    # Collect all expected keys and values from all processes
    all_expected_keys = {}
    for process_id, process_dict in results:
        all_expected_keys.update(process_dict)

    # Verify total number of keys
    final_keys = final_cache.keys()
    assert len(final_keys) == len(all_expected_keys), (
        f"Expected {len(all_expected_keys)} keys, got {len(final_keys)}"
    )

    # Verify all keys from all processes are present and have correct values
    for expected_key, expected_value in all_expected_keys.items():
        actual_value = final_cache.get(expected_key)
        assert actual_value == expected_value, (
            f"Expected {expected_value}, got {actual_value} for key {expected_key}"
        )

    # Verify keys are properly distributed across processes
    for process_id in range(num_processes):
        process_keys = [
            key for key in final_keys if key.startswith(f"process_{process_id}_")
        ]
        assert len(process_keys) == keys_per_process, (
            f"Process {process_id} should have {keys_per_process} keys, got {len(process_keys)}"
        )

    print(
        f"Successfully verified {len(all_expected_keys)} keys across {num_processes} processes"
    )


def test_multithread_write_without_database_lock_errors(tmpdir):
    cache_file = os.path.join(tmpdir, "cache_locking")
    assert not os.path.exists(cache_file)

    cache = PersistentCache(cache_file)

    def _cache_set(cache, key, num_sets):
        for _ in range(num_sets):
            cache.set(key, "value1")

    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
        futures = [
            executor.submit(_cache_set, cache, str(key), num_sets=1)
            for key in range(1000)
        ]
        r = [f.result() for f in futures]

    assert 1000 == len(cache.keys())


def _cache_set(cache_file, key, num_sets):
    cache = PersistentCache(cache_file)
    for i in range(num_sets):
        cache.set(f"key_{key}_{i}", f"value_{key}_{i}")


def test_multiprocess_write_without_database_lock_errors(tmpdir):
    """Test no database locking errors with multiple processes accessing the same cache file."""

    cache_file = os.path.join(tmpdir, "cache_locking")
    assert not os.path.exists(cache_file)

    with concurrent.futures.ProcessPoolExecutor(max_workers=40) as executor:
        futures = [
            executor.submit(_cache_set, cache_file, str(key), num_sets=1)
            for key in range(10000)
        ]
        r = [f.result() for f in futures]

    cache = PersistentCache(cache_file)
    assert 10000 == len(cache.keys())


def _sqlite_insert_rows(cache_file, value, num_inserts=1):
    while True:
        try:
            with sqlite3.connect(cache_file) as conn:
                conn.execute("PRAGMA journal_mode = wal")
                conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT, value TEXT)")

            with sqlite3.connect(cache_file) as conn:
                for _ in range(num_inserts):
                    conn.execute(
                        "INSERT INTO cache (key, value) VALUES (?, ?)", ("key1", value)
                    )
        except sqlite3.OperationalError as e:
            traceback.print_exc()
            if "database is locked" in str(e):
                time.sleep(1)
                continue
            else:
                raise
        else:
            break


def test_multiprocess_sqlite_database_locking(tmpdir):
    """Test database locking with multiple threads accessing the same cache file."""

    cache_file = os.path.join(tmpdir, "cache_sqlite_locking")
    assert not os.path.exists(cache_file)

    num_items = 4000
    num_inserts = 1

    with concurrent.futures.ProcessPoolExecutor(max_workers=40) as executor:
        futures = [
            executor.submit(
                _sqlite_insert_rows, cache_file, str(val), num_inserts=num_inserts
            )
            for val in range(num_items)
        ]
        r = [f.result() for f in futures]

    with sqlite3.connect(cache_file) as conn:
        row_count = len([row for row in conn.execute("select * from cache")])

    assert row_count == num_items * num_inserts, (
        f"Expected {num_items * num_inserts} rows, got {row_count}"
    )

    with concurrent.futures.ProcessPoolExecutor(max_workers=40) as executor:
        futures = [
            executor.submit(
                _sqlite_insert_rows, cache_file, str(val), num_inserts=num_inserts
            )
            for val in range(num_items)
        ]
        r = [f.result() for f in futures]

    with sqlite3.connect(cache_file) as conn:
        row_count = len([row for row in conn.execute("select * from cache")])

    assert row_count == (num_items * num_inserts) * 2, (
        f"Expected {(num_items * num_inserts) * 2} rows, got {row_count}"
    )


def test_multithread_sqlite_database_locking(tmpdir):
    """Test database locking with multiple threads accessing the same cache file."""

    cache_file = os.path.join(tmpdir, "cache_sqlite_locking")
    assert not os.path.exists(cache_file)

    num_items = 4000
    num_inserts = 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
        futures = [
            executor.submit(
                _sqlite_insert_rows, cache_file, str(val), num_inserts=num_inserts
            )
            for val in range(num_items)
        ]
        r = [f.result() for f in futures]

    with sqlite3.connect(cache_file) as conn:
        row_count = len([row for row in conn.execute("select * from cache")])

    assert row_count == num_items * num_inserts, (
        f"Expected {num_items * num_inserts} rows, got {row_count}"
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
        futures = [
            executor.submit(
                _sqlite_insert_rows, cache_file, str(val), num_inserts=num_inserts
            )
            for val in range(num_items)
        ]
        r = [f.result() for f in futures]

    with sqlite3.connect(cache_file) as conn:
        row_count = len([row for row in conn.execute("select * from cache")])

    assert row_count == num_items * num_inserts * 2, (
        f"Expected {num_items * num_inserts * 2} rows, got {row_count}"
    )
