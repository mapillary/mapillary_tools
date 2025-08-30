import concurrent.futures
import dbm
import multiprocessing
import os
import tempfile
import threading
import time
from pathlib import Path

import pytest

from mapillary_tools.history import PersistentCache


# DBM backends to test with
DBM_BACKENDS = ["dbm.sqlite3"]
# , "dbm.gnu", "dbm.ndbm", "dbm.dumb"]


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_basic_operations_with_backend(tmpdir, dbm_backend):
    """Test basic operations with different DBM backends.

    Note: This is a demonstration of pytest's parametrize feature.
    The actual PersistentCache class might not support specifying backends.
    """
    cache_file = os.path.join(tmpdir, dbm_backend)
    # Here you would use the backend if the cache implementation supported it
    cache = PersistentCache(cache_file)

    # Perform basic operations
    cache.set("test_key", "test_value")
    assert cache.get("test_key") == "test_value"

    # Add specific test logic for different backends if needed
    # This is just a placeholder to demonstrate pytest's parametrization


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_get_set(tmpdir, dbm_backend):
    """Test basic get and set operations."""
    cache_file = os.path.join(tmpdir, f"cache_get_set_{dbm_backend}")
    cache = PersistentCache(cache_file)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"
    assert cache.get("nonexistent_key") is None


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_expiration(tmpdir, dbm_backend):
    """Test that entries expire correctly."""
    cache_file = os.path.join(tmpdir, f"cache_expiration_{dbm_backend}")
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


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
@pytest.mark.parametrize(
    "expire_time,sleep_time,should_exist",
    [
        (1, 0.5, True),  # Should not expire yet
        (1, 1.5, False),  # Should expire
        (5, 2, True),  # Should not expire yet
    ],
)
def test_parametrized_expiration(
    tmpdir, dbm_backend, expire_time, sleep_time, should_exist
):
    """Test expiration with different timing combinations."""
    cache_file = os.path.join(
        tmpdir, f"cache_param_exp_{dbm_backend}_{expire_time}_{sleep_time}"
    )
    cache = PersistentCache(cache_file)

    key = f"key_expires_in_{expire_time}_sleeps_{sleep_time}"
    cache.set(key, "test_value", expires_in=expire_time)

    time.sleep(sleep_time)

    if should_exist:
        assert cache.get(key) == "test_value"
    else:
        assert cache.get(key) is None


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_clear_expired(tmpdir, dbm_backend):
    """Test clearing expired entries."""
    cache_file = os.path.join(tmpdir, f"cache_clear_expired_{dbm_backend}")
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


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_clear_expired_multiple(tmpdir, dbm_backend):
    """Test clearing multiple expired entries."""
    cache_file = os.path.join(tmpdir, f"cache_clear_multiple_{dbm_backend}")
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


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_clear_expired_all(tmpdir, dbm_backend):
    """Test clearing all expired entries."""
    cache_file = os.path.join(tmpdir, f"cache_clear_all_{dbm_backend}")
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


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_clear_expired_none(tmpdir, dbm_backend):
    """Test clearing when no entries are expired."""
    cache_file = os.path.join(tmpdir, f"cache_clear_none_{dbm_backend}")
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


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_clear_expired_empty(tmpdir, dbm_backend):
    """Test clearing expired entries on an empty cache."""
    cache_file = os.path.join(tmpdir, f"cache_clear_empty_{dbm_backend}")
    cache = PersistentCache(cache_file)

    # Test 5: Empty cache
    expired_keys = cache.clear_expired()

    # Check that no keys were cleared
    assert len(expired_keys) == 0


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_corrupted_data(tmpdir, dbm_backend):
    """Test handling of corrupted data."""
    cache_file = os.path.join(tmpdir, f"cache_corrupted_{dbm_backend}")
    cache = PersistentCache(cache_file)

    # Set valid entry
    cache.set("key1", "value1")

    # Corrupt the data by directly writing invalid JSON
    with dbm.open(cache_file, "c") as db:
        db["corrupted"] = b"not valid json"
        db["corrupted_dict"] = b'"not a dict"'

    # Check that corrupted entries are handled gracefully
    assert cache.get("corrupted") is None
    assert cache.get("corrupted_dict") is None

    # Valid entries should still work
    assert cache.get("key1") == "value1"

    # Clear expired should not crash on corrupted entries
    cache.clear_expired()


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_concurrency(tmpdir, dbm_backend):
    """Test concurrent access to the cache - fixed version."""
    cache_file = os.path.join(tmpdir, f"cache_concurrency_{dbm_backend}")
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


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_aggressive_concurrency_database_lock(tmpdir, dbm_backend):
    """Test aggressive concurrent access that might trigger database lock issues."""
    cache_file = os.path.join(tmpdir, f"cache_aggressive_{dbm_backend}")

    # Use a higher number of threads and operations to stress test
    num_threads = 50
    num_operations = 50
    errors = []

    def aggressive_worker(thread_id):
        """Worker that performs rapid database operations."""
        try:
            # Create a new cache instance per thread to simulate real-world usage
            thread_cache = PersistentCache(cache_file)

            for i in range(num_operations):
                key = f"thread_{thread_id}_op_{i}"
                value = f"value_{thread_id}_{i}"

                # Rapid set/get operations
                thread_cache.set(key, value, expires_in=1)
                retrieved = thread_cache.get(key)

                if retrieved != value:
                    errors.append(
                        f"Thread {thread_id}: Expected {value}, got {retrieved}"
                    )

                # Perform some operations that might cause contention
                if i % 5 == 0:
                    thread_cache.clear_expired()

                # Try to access keys from other threads
                if i % 3 == 0 and thread_id > 0:
                    other_key = f"thread_{thread_id - 1}_op_{i}"
                    thread_cache.get(other_key)

        except Exception as e:
            errors.append(f"Thread {thread_id} error: {str(e)}")

    # Run with high concurrency
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(aggressive_worker, i) for i in range(num_threads)]
        concurrent.futures.wait(futures)

    # Check for database lock errors or other issues
    database_lock_errors = [e for e in errors if "database is locked" in str(e).lower()]
    if database_lock_errors:
        pytest.fail(f"Database lock errors detected: {database_lock_errors}")

    if errors:
        pytest.fail(
            f"Concurrency errors detected: {errors[:10]}"
        )  # Show first 10 errors


# Global function for multiprocessing (needed for pickling)
def _multiprocess_worker(process_id, cache_file, num_ops):
    """Worker function for multiprocessing test."""
    import sys
    import traceback

    try:
        # Each process creates its own cache instance
        from mapillary_tools.history import PersistentCache

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

    with multiprocessing.Pool(processes=num_processes) as pool:
        results = pool.starmap(
            _multiprocess_worker,
            [(i, cache_file, num_operations) for i in range(num_processes)],
        )

    # Check for errors
    errors = [r for r in results if r is not None]
    database_lock_errors = [e for e in errors if "database is locked" in str(e).lower()]

    if database_lock_errors:
        pytest.fail(
            f"Database lock errors in multiprocess test: {database_lock_errors}"
        )

    if errors:
        pytest.fail(f"Multiprocess errors: {errors}")


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_rapid_file_creation_database_lock(tmpdir, dbm_backend):
    """Test rapid database file creation that might trigger lock issues."""
    base_path = os.path.join(tmpdir, f"rapid_creation_{dbm_backend}")

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


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_simultaneous_database_operations(tmpdir, dbm_backend):
    """Test simultaneous database operations that might cause locking."""
    cache_file = os.path.join(tmpdir, f"cache_simultaneous_{dbm_backend}")

    # Barrier to synchronize thread start
    barrier = threading.Barrier(10)
    errors = []

    def synchronized_worker(thread_id):
        """Worker that starts operations simultaneously."""
        try:
            cache = PersistentCache(cache_file)

            # Wait for all threads to be ready
            barrier.wait()

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

    # Start all threads simultaneously
    threads = []
    for i in range(10):
        thread = threading.Thread(target=synchronized_worker, args=(i,))
        threads.append(thread)
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Check for database lock errors
    database_lock_errors = [e for e in errors if "database is locked" in str(e).lower()]
    if database_lock_errors:
        pytest.fail(
            f"Database lock errors in simultaneous operations test: {database_lock_errors}"
        )

    if errors:
        pytest.fail(f"Simultaneous operation errors: {errors[:10]}")


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_stress_database_with_exceptions(tmpdir, dbm_backend):
    """Stress test that might trigger database lock issues with exception handling."""
    cache_file = os.path.join(tmpdir, f"cache_stress_{dbm_backend}")

    def stress_worker(thread_id):
        """Worker that performs operations and handles exceptions."""
        database_lock_count = 0
        other_errors = []

        cache = PersistentCache(cache_file)

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

                # Try to access the database file directly (might cause issues)
                if i % 15 == 0:
                    try:
                        with dbm.open(cache_file, flag="r") as db:
                            list(db.keys())
                    except Exception:
                        pass  # Ignore direct access errors

            except Exception as e:
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


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_decode_invalid_data(tmpdir, dbm_backend):
    """Test _decode method with invalid data."""
    cache_file = os.path.join(tmpdir, f"cache_decode_invalid_{dbm_backend}")
    cache = PersistentCache(cache_file)

    # Test with various invalid inputs
    result = cache._decode(b"not valid json")
    assert result == {}

    result = cache._decode(b'"string instead of dict"')
    assert result == {}


@pytest.mark.parametrize("dbm_backend", DBM_BACKENDS)
def test_is_expired(tmpdir, dbm_backend):
    """Test _is_expired method."""
    cache_file = os.path.join(tmpdir, f"cache_is_expired_{dbm_backend}")
    cache = PersistentCache(cache_file)

    # Test with various payloads
    assert cache._is_expired({"expires_at": time.time() - 10}) is True
    assert cache._is_expired({"expires_at": time.time() + 10}) is False
    assert cache._is_expired({}) is False
    assert cache._is_expired({"expires_at": "not a number"}) is False
    assert cache._is_expired({"expires_at": None}) is False
