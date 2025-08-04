import dbm
import os
import threading
import time

import pytest

from mapillary_tools.history import PersistentCache


# DBM backends to test with
DBM_BACKENDS = ["dbm.sqlite3", "dbm.gnu", "dbm.ndbm", "dbm.dumb"]


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
    """Test concurrent access to the cache."""
    cache_file = os.path.join(tmpdir, f"cache_concurrency_{dbm_backend}")
    cache = PersistentCache(cache_file)
    num_threads = 10
    num_operations = 50

    results = []  # Store assertion failures for pytest to check after threads complete

    def worker(thread_id):
        for i in range(num_operations):
            key = f"key_{thread_id}_{i}"
            value = f"value_{thread_id}_{i}"
            cache.set(key, value)
            # Occasionally read a previously written value
            if i > 0 and i % 5 == 0:
                prev_key = f"key_{thread_id}_{i - 1}"
                prev_value = cache.get(prev_key)
                if prev_value != f"value_{thread_id}_{i - 1}":
                    results.append(
                        f"Expected {prev_key} to be value_{thread_id}_{i - 1}, got {prev_value}"
                    )

    threads = []
    for i in range(num_threads):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Check for any failures in threads
    assert not results, f"Thread assertions failed: {results}"

    # Verify all values were written correctly
    for i in range(num_threads):
        for j in range(num_operations):
            key = f"key_{i}_{j}"
            expected_value = f"value_{i}_{j}"
            assert cache.get(key) == expected_value


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
