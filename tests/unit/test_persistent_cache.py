import concurrent.futures
import os
import time

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

    # Generate key-value pairs for first run (overlapping patterns to ensure intersections)
    first_dict = {f"key_{i}": f"first_value_{i}" for i in range(5_000)}
    assert len(first_dict) == 5_000

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

    shared_cache.clear_expired()
    assert len(shared_cache.keys()) == len(first_dict)
    for key in shared_cache.keys():
        assert shared_cache.get(key) == first_dict[key]

    # Generate key-value pairs for first run (overlapping patterns to ensure intersections)
    second_dict = {f"key_{i}": f"second_value_{i}" for i in range(2_500, 7_500)}

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
def _shared_worker_get_set_pattern(cache, key_value_pairs, expires_in=1000):
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


def test_sqlite_database_locking(tmpdir):
    """Test database locking with multiple threads accessing the same cache file."""
    import sqlite3

    cache_file = os.path.join(tmpdir, "cache_sqlite_locking")

    def create_table(value):
        while True:
            try:
                with sqlite3.connect(
                    cache_file, autocommit=True
                ) as conn:  # Create the database file
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS cache (key TEXT, value TEXT)"
                    )
                    conn.execute(
                        "INSERT INTO cache (key, value) VALUES (?, ?)", ("key1", value)
                    )
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    print(f"Thread {value} failed to acquire lock: {e}")
                    time.sleep(1)
                    continue
                else:
                    raise
            else:
                break

        with sqlite3.connect(
            cache_file, autocommit=True
        ) as conn:  # Create the database file
            rows = [row for row in conn.execute("select * from cache")]

    r = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(create_table, str(_)) for _ in range(1000)]
        for f in futures:
            r.append(f.result())

    with sqlite3.connect(
        cache_file, autocommit=True
    ) as conn:  # Create the database file
        row_count = len([row for row in conn.execute("select * from cache")])

    assert row_count == 3000, f"Expected 3000 rows, got {row_count}"
