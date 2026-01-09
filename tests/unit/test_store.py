# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import os
import sqlite3
import tempfile

import pytest
from mapillary_tools.store import KeyValueStore


def test_basic_dict_operations(tmpdir):
    """Test that KeyValueStore behaves like a dict for basic operations."""
    db_path = tmpdir.join("test.db")

    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        # Test setting and getting - strings are stored as bytes
        store["key1"] = "value1"
        store["key2"] = "value2"

        assert store["key1"] == b"value1"
        assert store["key2"] == b"value2"

        # Test length
        assert len(store) == 2

        # Test iteration - keys come back as bytes
        keys = list(store)
        assert set(keys) == {b"key1", b"key2"}

        # Test keys() method
        assert set(store.keys()) == {b"key1", b"key2"}

        # Test deletion
        del store["key1"]
        assert len(store) == 1
        assert "key1" not in store
        assert "key2" in store


def test_keyerror_on_missing_key(tmpdir):
    """Test that KeyError is raised for missing keys."""
    db_path = tmpdir.join("test.db")

    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        with pytest.raises(KeyError):
            _ = store["nonexistent"]

        with pytest.raises(KeyError):
            del store["nonexistent"]


def test_flag_modes(tmpdir):
    """Test different flag modes."""
    db_path = tmpdir.join("test.db")

    # Test 'n' flag - creates new database
    with KeyValueStore(str(db_path), flag="n", mode=0o666) as store:
        store["key"] = "value"
        assert store["key"] == b"value"

    # Test 'c' flag - opens existing or creates new
    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        assert store["key"] == b"value"  # Should still exist
        store["key2"] = "value2"

    # Test 'w' flag - opens existing for read/write
    with KeyValueStore(str(db_path), flag="w", mode=0o666) as store:
        assert store["key"] == b"value"
        assert store["key2"] == b"value2"
        store["key3"] = "value3"

    # Test 'r' flag - read-only mode
    with KeyValueStore(str(db_path), flag="r", mode=0o666) as store:
        # Getter should work in readonly mode
        assert store["key"] == b"value"
        assert store["key2"] == b"value2"
        assert store["key3"] == b"value3"
        assert len(store) == 3

        # Iteration should work in readonly mode
        keys = set(store.keys())
        assert keys == {b"key", b"key2", b"key3"}

        # But setter should fail
        with pytest.raises(sqlite3.OperationalError):
            store["new_key"] = "new_value"


def test_readonly_mode_comprehensive(tmpdir):
    """Test comprehensive readonly mode functionality."""
    db_path = tmpdir.join("readonly_test.db")

    # First, create and populate the database
    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        store["test_key"] = "test_value"
        store["another_key"] = "another_value"
        store[b"binary_key"] = b"binary_value"
        store[123] = "numeric_key_value"

    # Now open in readonly mode and test all read operations
    with KeyValueStore(str(db_path), flag="r", mode=0o666) as readonly_store:
        # Test basic getitem - strings come back as bytes
        assert readonly_store["test_key"] == b"test_value"
        assert readonly_store["another_key"] == b"another_value"
        assert readonly_store[b"binary_key"] == b"binary_value"
        assert readonly_store[123] == b"numeric_key_value"

        # Test len
        assert len(readonly_store) == 4

        # Test iteration - keys come back as bytes
        all_keys = set(readonly_store)
        assert all_keys == {b"test_key", b"another_key", b"binary_key", b"123"}

        # Test keys() method
        assert set(readonly_store.keys()) == all_keys

        # Test containment
        assert "test_key" in readonly_store
        assert "nonexistent" not in readonly_store

        # Test that write operations fail
        with pytest.raises(
            sqlite3.OperationalError, match="attempt to write a readonly database"
        ):
            readonly_store["new_key"] = "should_fail"

        with pytest.raises(
            sqlite3.OperationalError, match="attempt to write a readonly database"
        ):
            del readonly_store["test_key"]


def test_invalid_flag():
    """Test that invalid flags raise ValueError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")

        with pytest.raises(ValueError, match="Flag must be one of"):
            KeyValueStore(db_path, flag="x", mode=0o666)


def test_context_manager(tmpdir):
    """Test context manager functionality."""
    db_path = tmpdir.join("context_test.db")

    # Test normal context manager usage
    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        store["key"] = "value"
        assert store["key"] == b"value"

    # After exiting context, store should be closed
    with pytest.raises(
        sqlite3.ProgrammingError, match="Cannot operate on a closed database"
    ):
        _ = store["key"]


def test_manual_close(tmpdir):
    """Test manual close functionality."""
    db_path = tmpdir.join("close_test.db")

    store = KeyValueStore(str(db_path), flag="c", mode=0o666)
    store["key"] = "value"
    assert store["key"] == b"value"

    store.close()

    # After closing, operations should fail
    with pytest.raises(
        sqlite3.ProgrammingError, match="Cannot operate on a closed database"
    ):
        _ = store["key"]

    with pytest.raises(
        sqlite3.ProgrammingError, match="Cannot operate on a closed database"
    ):
        store["new_key"] = "new_value"


def test_open_function(tmpdir):
    """Test the open() function."""
    db_path = tmpdir.join("open_test.db")

    # Test default parameters
    with KeyValueStore(str(db_path), flag="c") as store:
        store["key"] = "value"
        assert store["key"] == b"value"

    # Test with explicit parameters
    with KeyValueStore(str(db_path), flag="w", mode=0o644) as store:
        assert store["key"] == b"value"
        store["key2"] = "value2"

    # Test readonly
    with KeyValueStore(str(db_path), flag="r") as store:
        assert store["key"] == b"value"
        assert store["key2"] == b"value2"


def test_binary_and_various_key_types(tmpdir):
    """Test that the store can handle various key and value types."""
    db_path = tmpdir.join("types_test.db")

    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        # String keys and values
        store["string_key"] = "string_value"

        # Binary keys and values
        store[b"binary_key"] = b"binary_value"

        # Numeric keys
        store[123] = "numeric_key"
        store["numeric_value"] = 456

        # Mixed types - use different key names to avoid collision
        store[b"mixed_binary"] = "string_value_for_binary_key"
        store["mixed_string"] = b"binary_value_for_string_key"

        # Verify all work - strings come back as bytes
        assert store["string_key"] == b"string_value"
        assert store[b"binary_key"] == b"binary_value"
        assert store[123] == b"numeric_key"
        assert store["numeric_value"] == b"456"
        assert store[b"mixed_binary"] == b"string_value_for_binary_key"
        assert store["mixed_string"] == b"binary_value_for_string_key"


def test_overwrite_behavior(tmpdir):
    """Test that values can be overwritten."""
    db_path = tmpdir.join("overwrite_test.db")

    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        store["key"] = "original_value"
        assert store["key"] == b"original_value"

        store["key"] = "new_value"
        assert store["key"] == b"new_value"

        # Length should still be 1
        assert len(store) == 1


def test_empty_store(tmpdir):
    """Test behavior with empty store."""
    db_path = tmpdir.join("empty_test.db")

    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        assert len(store) == 0
        assert list(store) == []
        assert store.keys() == []

        with pytest.raises(KeyError):
            _ = store["any_key"]


def test_new_flag_overwrites_existing(tmpdir):
    """Test that 'n' flag creates a new database, overwriting existing."""
    db_path = tmpdir.join("new_flag_test.db")

    # Create initial database
    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        store["key"] = "original"

    # Open with 'n' flag should create new database
    with KeyValueStore(str(db_path), flag="n", mode=0o666) as store:
        assert len(store) == 0  # Should be empty
        store["key"] = "new"

    # Verify the old data is gone
    with KeyValueStore(str(db_path), flag="r", mode=0o666) as store:
        assert store["key"] == b"new"
        assert len(store) == 1


def test_persistence_across_sessions(tmpdir):
    """Test that data persists across different sessions."""
    db_path = tmpdir.join("persistence_test.db")

    # First session
    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        store["persistent_key"] = "persistent_value"
        store["another_key"] = "another_value"

    # Second session
    with KeyValueStore(str(db_path), flag="r", mode=0o666) as store:
        assert store["persistent_key"] == b"persistent_value"
        assert store["another_key"] == b"another_value"
        assert len(store) == 2


def test_dict_like_membership(tmpdir):
    """Test membership operations work like dict."""
    db_path = tmpdir.join("membership_test.db")

    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        store["exists"] = "value"

        assert "exists" in store
        assert "does_not_exist" not in store

        # Test with different key types
        store[123] = "numeric"
        store[b"binary"] = "binary_value"

        assert 123 in store
        assert b"binary" in store
        assert 456 not in store
        assert b"not_there" not in store


def test_readonly_mode_nonexistent_file(tmpdir):
    """Test readonly mode with a non-existent file."""
    db_path = tmpdir.join("nonexistent.db")

    # Try to open a non-existent file in readonly mode
    # This should raise an error since the file doesn't exist
    with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
        KeyValueStore(str(db_path), flag="r", mode=0o666)


def test_readonly_mode_empty_database(tmpdir):
    """Test readonly mode with an empty database."""
    db_path = tmpdir.join("empty_readonly.db")

    # First create an empty database
    with KeyValueStore(str(db_path), flag="c", mode=0o666) as store:
        pass  # Create empty database

    # Now open it in readonly mode
    with KeyValueStore(str(db_path), flag="r", mode=0o666) as readonly_store:
        # Getting a non-existent value should raise KeyError
        with pytest.raises(KeyError):
            _ = readonly_store["nonexistent_key"]

        # Length should be 0
        assert len(readonly_store) == 0

        # Keys should be empty
        assert list(readonly_store.keys()) == []

        # Iteration should be empty
        assert list(readonly_store) == []

        # Membership test should return False
        assert "any_key" not in readonly_store
