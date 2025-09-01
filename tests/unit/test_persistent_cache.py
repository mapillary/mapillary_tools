import concurrent.futures
import os
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
    """Test handling of corrupted data."""
    cache_file = os.path.join(tmpdir, f"cache_corrupted")
    cache = PersistentCache(cache_file)

    # Set valid entry
    cache.set("key1", "value1")

    # Test the _decode method directly with corrupted data to simulate corruption
    # This tests the error handling without directly manipulating the database
    corrupted_result = cache._decode(b"not valid json")
    assert corrupted_result == {}

    corrupted_dict_result = cache._decode(b'"not a dict"')
    assert corrupted_dict_result == {}

    # Valid entries should still work
    assert cache.get("key1") == "value1"

    # Clear expired should not crash
    cache.clear_expired()


def test_concurrency(tmpdir):
    """Test concurrent access to the cache - fixed version."""
    cache_file = os.path.join(tmpdir, f"cache_concurrency")

    cache = PersistentCache(cache_file)
    num_threads = 20
    num_operations = 10

    results = []  # Store assertion failures for pytest to check after threads complete

    def worker(thread_id):
        # Fixed: Don't overwrite thread_id parameter
        for i in range(num_operations):
            key = f"key_{thread_id}_{i}"
            value = f"value_{thread_id}_{i}"
            if cache.get(key) is None:
                cache.set(key, value)
            # Occasionally read a previously written value
            if i > 0 and i % 2 == 0:
                prev_key = f"key_{thread_id}_{i - 1}"
                prev_value = cache.get(prev_key)
                if prev_value != f"value_{thread_id}_{i - 1}":
                    results.append(
                        f"Expected {prev_key} to be value_{thread_id}_{i - 1}, got {prev_value}"
                    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        list(executor.map(worker, range(num_threads)))

    # Check for any failures in threads
    assert not results, f"Thread assertions failed: {results}"


# Global function for multiprocessing (needed for pickling)
def _multiprocess_worker(process_id, cache_file, num_ops):
    """Worker function for multiprocessing test."""
    try:
        # Each process creates its own cache instance
        cache = PersistentCache(cache_file)

        for i in range(num_ops):
            key = f"proc_{process_id}_op_{i}"
            value = f"value_{process_id}_{i}"

            # Rapid operations that might cause database locking
            cache.set(key, value, expires_in=2)
            retrieved = cache.get(key)

            if retrieved != value:
                return f"Process {process_id}: Expected {value}, got {retrieved}"

            # Operations that might cause contention
            if i % 3 == 0:
                cache.clear_expired()

            # Try to read from other processes
            if i % 5 == 0 and process_id > 0:
                other_key = f"proc_{process_id - 1}_op_{i}"
                cache.get(other_key)

    except Exception as e:
        return f"Process {process_id} error: {str(e)} - {traceback.format_exc()}"

    return None


def test_multiprocess_database_lock(tmpdir):
    """Test multiprocess access that might trigger database lock issues."""
    cache_file = os.path.join(tmpdir, "cache_multiprocess")

    # Use multiprocessing to create real process contention
    num_processes = 8
    num_operations = 20

    with concurrent.futures.ProcessPoolExecutor(max_workers=num_processes) as executor:
        futures = [
            executor.submit(_multiprocess_worker, i, cache_file, num_operations)
            for i in range(num_processes)
        ]
        results = [
            future.result() for future in concurrent.futures.as_completed(futures)
        ]

    # Check for errors
    errors = [r for r in results if r is not None]
    database_lock_errors = [e for e in errors if "database is locked" in str(e).lower()]

    if database_lock_errors:
        pytest.fail(
            f"Database lock errors in multiprocess test: {database_lock_errors}"
        )

    if errors:
        pytest.fail(f"Multiprocess errors: {errors}")


def test_rapid_file_creation_database_lock(tmpdir):
    """Test rapid database file creation that might trigger lock issues."""
    base_path = os.path.join(tmpdir, f"rapid_creation")

    def rapid_creator(thread_id):
        """Create and use cache files rapidly."""
        errors = []
        try:
            for i in range(10):
                # Create a new cache file for each operation
                cache_file = f"{base_path}_{thread_id}_{i}"
                cache = PersistentCache(cache_file)

                # Perform operations immediately after creation
                cache.set("test_key", f"test_value_{thread_id}_{i}")
                result = cache.get("test_key")

                if result != f"test_value_{thread_id}_{i}":
                    errors.append(
                        f"Thread {thread_id}, iteration {i}: Expected test_value_{thread_id}_{i}, got {result}"
                    )

        except Exception as e:
            errors.append(f"Thread {thread_id} error: {str(e)}")

        return errors

    # Run multiple threads creating cache files rapidly
    num_threads = 20
    all_errors = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(rapid_creator, i) for i in range(num_threads)]
        for future in concurrent.futures.as_completed(futures):
            errors = future.result()
            all_errors.extend(errors)

    # Check for database lock errors
    database_lock_errors = [
        e for e in all_errors if "database is locked" in str(e).lower()
    ]
    if database_lock_errors:
        pytest.fail(
            f"Database lock errors in rapid creation test: {database_lock_errors}"
        )

    if all_errors:
        pytest.fail(f"Rapid creation errors: {all_errors[:5]}")  # Show first 5 errors


def test_simultaneous_database_operations(tmpdir):
    """Test simultaneous database operations that might cause locking."""
    cache_file = os.path.join(tmpdir, f"cache_simultaneous")

    errors = []

    def synchronized_worker(thread_id):
        """Worker that starts operations simultaneously."""
        try:
            cache = PersistentCache(cache_file)

            # All threads perform operations at the same time
            for i in range(20):
                key = f"sync_{thread_id}_{i}"
                value = f"value_{thread_id}_{i}"

                # Simultaneous write operations
                cache.set(key, value)

                # Immediate read back
                result = cache.get(key)
                if result != value:
                    errors.append(f"Thread {thread_id}: Expected {value}, got {result}")

                # Mixed operations
                if i % 2 == 0:
                    cache.clear_expired()

        except Exception as e:
            errors.append(f"Thread {thread_id} error: {str(e)}")

    # Start all threads simultaneously using ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(synchronized_worker, i) for i in range(10)]
        concurrent.futures.wait(futures)

    # Check for database lock errors
    database_lock_errors = [e for e in errors if "database is locked" in str(e).lower()]
    if database_lock_errors:
        pytest.fail(
            f"Database lock errors in simultaneous operations test: {database_lock_errors}"
        )

    if errors:
        pytest.fail(f"Simultaneous operation errors: {errors[:10]}")


def test_stress_database_with_exceptions(tmpdir):
    """Stress test that might trigger database lock issues with exception handling."""
    cache_file = os.path.join(tmpdir, f"cache_stress")
    cache = PersistentCache(cache_file)

    def stress_worker(thread_id):
        """Worker that performs operations and handles exceptions."""
        database_lock_count = 0
        other_errors = []

        for i in range(100):  # More operations to increase chance of lock
            try:
                key = f"stress_{thread_id}_{i}"
                value = f"value_{thread_id}_{i}"

                # Rapid operations
                cache.set(key, value, expires_in=1)
                cache.get(key)

                # Operations that might cause contention
                if i % 10 == 0:
                    cache.clear_expired()

                # Additional operations that might cause contention
                if i % 15 == 0:
                    # Use cache.keys() instead of direct dbm access
                    try:
                        list(cache.keys())
                    except Exception:
                        pass  # Ignore access errors

            except Exception as e:
                # raise e
                error_msg = str(e).lower()
                if "database is locked" in error_msg:
                    database_lock_count += 1
                else:
                    other_errors.append(f"Thread {thread_id}, op {i}: {str(e)}")

        return database_lock_count, other_errors

    # Run stress test
    num_threads = 15
    total_lock_errors = 0
    all_other_errors = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(stress_worker, i) for i in range(num_threads)]
        for future in concurrent.futures.as_completed(futures):
            lock_count, other_errors = future.result()
            total_lock_errors += lock_count
            all_other_errors.extend(other_errors)

    # Report results
    if total_lock_errors > 0:
        pytest.fail(
            f"Database lock errors detected: {total_lock_errors} total lock errors"
        )

    if all_other_errors:
        pytest.fail(f"Other stress test errors: {all_other_errors[:5]}")


def test_shared_cache_instance_database_lock(tmpdir):
    """Test shared cache instance across threads - reproduces real uploader.py usage pattern."""
    cache_file = os.path.join(tmpdir, f"cache_shared")

    # Create a single shared cache instance (like in uploader.py)
    shared_cache = PersistentCache(cache_file)
    shared_cache.clear_expired()

    # Use higher numbers to increase chance of database lock
    num_threads = 30
    num_operations = 100
    errors = []

    def shared_cache_worker(thread_id):
        """Worker that uses the shared cache instance (like CachedImageUploader.upload)."""
        try:
            for i in range(num_operations):
                key = f"shared_thread_{thread_id}_op_{i}"
                value = f"shared_value_{thread_id}_{i}"

                # Simulate the pattern from CachedImageUploader:
                # 1. Check cache first (_get_cached_file_handle)
                cached_value = shared_cache.get(key)

                if cached_value is None:
                    # 2. Set new value (_set_file_handle_cache)
                    shared_cache.set(key, value, expires_in=2)
                    retrieved = shared_cache.get(key)

                    if retrieved != value:
                        errors.append(
                            f"Thread {thread_id}: Expected {value}, got {retrieved}"
                        )
                else:
                    # 3. Update cache with existing value (_set_file_handle_cache)
                    shared_cache.set(key, cached_value, expires_in=2)

                # Occasional cleanup operations
                if i % 20 == 0:
                    shared_cache.clear_expired()

                # Cross-thread access pattern
                if i % 7 == 0 and thread_id > 0:
                    other_key = f"shared_thread_{thread_id - 1}_op_{i}"
                    shared_cache.get(other_key)

        except Exception as e:
            errors.append(f"Thread {thread_id} error: {str(e)}")
            print(e, traceback.format_exc())

    # Run all threads using the same shared cache instance
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(shared_cache_worker, i) for i in range(num_threads)]
        concurrent.futures.wait(futures)

    # Check for database lock errors
    database_lock_errors = [e for e in errors if "database is locked" in str(e).lower()]
    if database_lock_errors:
        pytest.fail(
            f"Database lock errors with shared cache instance: {database_lock_errors}"
        )

    # Check for data consistency errors (values not persisting correctly)
    data_consistency_errors = [e for e in errors if "Expected" in e and "got None" in e]
    if data_consistency_errors:
        pytest.fail(
            f"Data consistency errors with shared cache (race conditions): {data_consistency_errors[:5]}"
        )

    if errors:
        pytest.fail(f"Other shared cache errors: {errors[:10]}")  # Show first 10 errors


def test_decode_invalid_data(tmpdir):
    """Test _decode method with invalid data."""
    cache_file = os.path.join(tmpdir, f"cache_decode_invalid")
    cache = PersistentCache(cache_file)

    # Test with various invalid inputs
    result = cache._decode(b"not valid json")
    assert result == {}

    result = cache._decode(b'"string instead of dict"')
    assert result == {}


def test_is_expired(tmpdir):
    """Test _is_expired method."""
    cache_file = os.path.join(tmpdir, f"cache_is_expired")
    cache = PersistentCache(cache_file)

    # Test with various payloads
    assert cache._is_expired({"expires_at": time.time() - 10}) is True
    assert cache._is_expired({"expires_at": time.time() + 10}) is False
    assert cache._is_expired({}) is False
    assert cache._is_expired({"expires_at": "not a number"}) is False
    assert cache._is_expired({"expires_at": None}) is False


# Shared worker functions for concurrency tests
def _shared_worker_get_set_pattern(
    worker_id, cache, num_operations, key_prefix="worker"
):
    """Shared worker implementation: get key -> if not exist then set key=value."""
    errors = []
    try:
        for i in range(num_operations):
            key = f"{key_prefix}_{worker_id}_{i}"
            value = f"value_{worker_id}_{i}"

            # Pattern: get a key -> if not exist then set key=value
            existing_value = cache.get(key)
            if existing_value is None:
                cache.set(key, value, expires_in=10)

            # Verify the value was set correctly
            retrieved_value = cache.get(key)
            if retrieved_value != value:
                errors.append(
                    f"Worker {worker_id}: Expected {value}, got {retrieved_value}"
                )

    except Exception as e:
        errors.append(f"Worker {worker_id} error: {str(e)}")

    return errors


def _multiprocess_worker_get_set_pattern(args):
    """Multiprocess worker wrapper for the shared worker pattern."""
    worker_id, cache_file, num_operations, key_prefix = args
    try:
        # Each process creates its own cache instance pointing to the same file
        cache = PersistentCache(cache_file)
        return _shared_worker_get_set_pattern(
            worker_id, cache, num_operations, key_prefix
        )
    except Exception as e:
        return [f"Process {worker_id} error: {str(e)} - {traceback.format_exc()}"]


def _mixed_operations_worker(args):
    """Worker that performs mixed operations with get->set pattern."""
    worker_id, cache_file, num_operations, run_prefix = args
    errors = []
    try:
        cache = PersistentCache(cache_file)

        for i in range(num_operations):
            key = f"{run_prefix}_mixed_{worker_id}_{i}"
            value = f"mixed_value_{worker_id}_{i}"

            # Pattern: get a key -> if not exist then set key=value
            existing_value = cache.get(key)
            if existing_value is None:
                cache.set(key, value, expires_in=15)

            # Mixed operations: also try to read from other workers
            if i % 5 == 0 and worker_id > 0:
                other_key = f"{run_prefix}_mixed_{worker_id - 1}_{i}"
                cache.get(other_key)

            # Periodic cleanup
            if i % 10 == 0:
                cache.clear_expired()

    except Exception as e:
        errors.append(f"Process {worker_id} error: {str(e)}")

    return errors


def test_multithread_shared_cache_get_set_pattern(tmpdir):
    """Test multithreaded access with shared cache instance using get->set pattern."""
    cache_file = os.path.join(tmpdir, "cache_multithread_shared")

    # Initialize cache once and share across all workers
    shared_cache = PersistentCache(cache_file)

    # Clear expired before first concurrent run
    shared_cache.clear_expired()

    num_threads = 10
    num_operations = 20
    all_errors = []

    # First concurrent run
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [
            executor.submit(
                _shared_worker_get_set_pattern, i, shared_cache, num_operations, "run1"
            )
            for i in range(num_threads)
        ]
        for future in concurrent.futures.as_completed(futures):
            errors = future.result()
            all_errors.extend(errors)

    # Clear expired between concurrent runs
    expired_keys_1 = shared_cache.clear_expired()
    assert isinstance(expired_keys_1, list), "clear_expired should return a list"

    # Second concurrent run
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [
            executor.submit(
                _shared_worker_get_set_pattern, i, shared_cache, num_operations, "run2"
            )
            for i in range(num_threads)
        ]
        for future in concurrent.futures.as_completed(futures):
            errors = future.result()
            all_errors.extend(errors)

    # Clear expired after second concurrent run
    expired_keys_2 = shared_cache.clear_expired()
    assert isinstance(expired_keys_2, list), "clear_expired should return a list"

    # Assertions using keys() and counts
    all_keys = list(shared_cache.keys())
    expected_keys_count = num_threads * num_operations * 2  # Two runs

    assert (
        len(all_keys) == expected_keys_count
    ), f"Expected {expected_keys_count} keys, got {len(all_keys)}"

    # Verify key patterns
    run1_keys = [k for k in all_keys if b"run1" in k]
    run2_keys = [k for k in all_keys if b"run2" in k]

    assert len(run1_keys) == num_threads * num_operations
    assert len(run2_keys) == num_threads * num_operations

    # Check for any worker errors
    assert not all_errors, f"Worker errors occurred: {all_errors}"


def test_multiprocess_shared_file_get_set_pattern(tmpdir):
    """Test multiprocess access with shared cache file using get->set pattern."""
    cache_file = os.path.join(tmpdir, "cache_multiprocess_shared")

    # Initialize cache and clear expired before first concurrent run
    init_cache = PersistentCache(cache_file)
    init_cache.clear_expired()

    num_processes = 6
    num_operations = 15

    # First concurrent run
    with concurrent.futures.ProcessPoolExecutor(max_workers=num_processes) as executor:
        args_list = [
            (i, cache_file, num_operations, "proc_run1") for i in range(num_processes)
        ]
        futures = [
            executor.submit(_multiprocess_worker_get_set_pattern, args)
            for args in args_list
        ]
        results_1 = [
            future.result() for future in concurrent.futures.as_completed(futures)
        ]

    # Clear expired between concurrent runs
    expired_keys_1 = init_cache.clear_expired()
    assert isinstance(expired_keys_1, list), "clear_expired should return a list"

    # Second concurrent run
    with concurrent.futures.ProcessPoolExecutor(max_workers=num_processes) as executor:
        args_list = [
            (i, cache_file, num_operations, "proc_run2") for i in range(num_processes)
        ]
        futures = [
            executor.submit(_multiprocess_worker_get_set_pattern, args)
            for args in args_list
        ]
        results_2 = [
            future.result() for future in concurrent.futures.as_completed(futures)
        ]

    # Clear expired after second concurrent run
    expired_keys_2 = init_cache.clear_expired()
    assert isinstance(expired_keys_2, list), "clear_expired should return a list"

    # Collect all errors from both runs
    all_errors = []
    for result in results_1 + results_2:
        all_errors.extend(result)

    # Assertions using keys() and counts
    all_keys = list(init_cache.keys())
    expected_keys_count = num_processes * num_operations * 2  # Two runs

    assert (
        len(all_keys) == expected_keys_count
    ), f"Expected {expected_keys_count} keys, got {len(all_keys)}"

    # Verify key patterns
    run1_keys = [k for k in all_keys if b"proc_run1" in k]
    run2_keys = [k for k in all_keys if b"proc_run2" in k]

    assert len(run1_keys) == num_processes * num_operations
    assert len(run2_keys) == num_processes * num_operations

    # Check for database lock errors specifically
    database_lock_errors = [
        e for e in all_errors if "database is locked" in str(e).lower()
    ]
    if database_lock_errors:
        pytest.fail(
            f"Database lock errors in multiprocess test: {database_lock_errors}"
        )

    # Check for any other errors
    assert not all_errors, f"Process errors occurred: {all_errors}"


def test_multithread_high_contention_get_set_pattern(tmpdir):
    """Test high contention multithreaded access with shared cache using get->set pattern."""
    cache_file = os.path.join(tmpdir, "cache_multithread_contention")

    # Initialize cache once and share across all workers
    shared_cache = PersistentCache(cache_file)

    # Clear expired before first concurrent run
    shared_cache.clear_expired()

    num_threads = 20
    num_operations = 50
    all_errors = []

    def high_contention_worker(worker_id, run_prefix):
        """Worker with higher contention - accessing overlapping keys."""
        errors = []
        try:
            for i in range(num_operations):
                # Use overlapping keys to increase contention
                key = f"{run_prefix}_shared_{i % 10}"  # Only 10 unique keys per run
                value = f"value_{worker_id}_{i}"

                # Pattern: get a key -> if not exist then set key=value
                existing_value = shared_cache.get(key)
                if existing_value is None:
                    shared_cache.set(key, value, expires_in=10)

                # Occasional clear_expired to add more contention
                if i % 25 == 0:
                    shared_cache.clear_expired()

        except Exception as e:
            errors.append(f"Worker {worker_id} error: {str(e)}")

        return errors

    # First concurrent run with high contention
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [
            executor.submit(high_contention_worker, i, "contention_run1")
            for i in range(num_threads)
        ]
        for future in concurrent.futures.as_completed(futures):
            errors = future.result()
            all_errors.extend(errors)

    # Clear expired between concurrent runs
    expired_keys_1 = shared_cache.clear_expired()
    assert isinstance(expired_keys_1, list), "clear_expired should return a list"
    keys_after_run1 = list(shared_cache.keys())

    # Second concurrent run with high contention
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [
            executor.submit(high_contention_worker, i, "contention_run2")
            for i in range(num_threads)
        ]
        for future in concurrent.futures.as_completed(futures):
            errors = future.result()
            all_errors.extend(errors)

    # Clear expired after second concurrent run
    expired_keys_2 = shared_cache.clear_expired()
    assert isinstance(expired_keys_2, list), "clear_expired should return a list"
    keys_after_run2 = list(shared_cache.keys())

    # Assertions using keys() and counts
    # With overlapping keys, we expect at most 10 keys per run (due to key overlap)
    assert (
        len(keys_after_run1) <= 10
    ), f"Expected at most 10 keys after run1, got {len(keys_after_run1)}"
    assert (
        len(keys_after_run2) <= 20
    ), f"Expected at most 20 keys after run2, got {len(keys_after_run2)}"

    # Verify key patterns exist
    run1_keys = [k for k in keys_after_run2 if b"contention_run1" in k]
    run2_keys = [k for k in keys_after_run2 if b"contention_run2" in k]

    assert len(run1_keys) > 0, "Should have some keys from run1"
    assert len(run2_keys) > 0, "Should have some keys from run2"

    # Check for any worker errors
    assert not all_errors, f"Worker errors occurred: {all_errors}"


def test_multiprocess_mixed_operations_get_set_pattern(tmpdir):
    """Test multiprocess with mixed operations using get->set pattern."""
    cache_file = os.path.join(tmpdir, "cache_multiprocess_mixed")

    # Initialize cache and clear expired before first concurrent run
    init_cache = PersistentCache(cache_file)
    init_cache.clear_expired()

    num_processes = 8
    num_operations = 25

    # First concurrent run
    with concurrent.futures.ProcessPoolExecutor(max_workers=num_processes) as executor:
        args_list = [
            (i, cache_file, num_operations, "mixed_run1") for i in range(num_processes)
        ]
        futures = [
            executor.submit(_mixed_operations_worker, args) for args in args_list
        ]
        results_1 = [
            future.result() for future in concurrent.futures.as_completed(futures)
        ]

    # Clear expired between concurrent runs
    expired_keys_1 = init_cache.clear_expired()
    assert isinstance(expired_keys_1, list), "clear_expired should return a list"
    keys_after_run1 = list(init_cache.keys())

    # Verify first run results
    expected_keys_run1 = num_processes * num_operations
    assert (
        len(keys_after_run1) == expected_keys_run1
    ), f"Expected {expected_keys_run1} keys after run1, got {len(keys_after_run1)}"

    # Second concurrent run
    with concurrent.futures.ProcessPoolExecutor(max_workers=num_processes) as executor:
        args_list = [
            (i, cache_file, num_operations, "mixed_run2") for i in range(num_processes)
        ]
        futures = [
            executor.submit(_mixed_operations_worker, args) for args in args_list
        ]
        results_2 = [
            future.result() for future in concurrent.futures.as_completed(futures)
        ]

    # Clear expired after second concurrent run
    expired_keys_2 = init_cache.clear_expired()
    assert isinstance(expired_keys_2, list), "clear_expired should return a list"
    keys_after_run2 = list(init_cache.keys())

    # Collect all errors from both runs
    all_errors = []
    for result in results_1 + results_2:
        all_errors.extend(result)

    # Assertions using keys() and counts
    expected_keys_count = num_processes * num_operations * 2  # Two runs

    assert (
        len(keys_after_run2) == expected_keys_count
    ), f"Expected {expected_keys_count} keys, got {len(keys_after_run2)}"

    # Verify key patterns
    run1_keys = [k for k in keys_after_run2 if b"mixed_run1" in k]
    run2_keys = [k for k in keys_after_run2 if b"mixed_run2" in k]

    assert len(run1_keys) == num_processes * num_operations
    assert len(run2_keys) == num_processes * num_operations

    # Check for database lock errors specifically
    database_lock_errors = [
        e for e in all_errors if "database is locked" in str(e).lower()
    ]
    if database_lock_errors:
        pytest.fail(
            f"Database lock errors in mixed operations test: {database_lock_errors}"
        )

    # Check for any other errors
    assert not all_errors, f"Mixed operations errors occurred: {all_errors}"
