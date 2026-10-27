# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import errno
import os
import stat
import sys
import typing as T
from pathlib import Path

import py.path
import pytest
from mapillary_tools import config


def test_config_list_all_users(tmpdir: py.path.local):
    c = tmpdir.join("empty_config.ini")
    x = config.list_all_users(config_path=str(c))
    assert not x

    config.update_config(
        "hello",
        T.cast(
            T.Any,
            {
                "ThisIsOption": "1",
            },
        ),
        config_path=str(c),
    )

    x = config.list_all_users(config_path=str(c))
    assert len(x) == 1
    assert x["hello"] == {"ThisIsOption": "1"}


def test_update_config(tmpdir: py.path.local):
    c = tmpdir.join("empty_config.ini")
    config.update_config(
        "world", T.cast(T.Any, {"ThisIsOption": "hello"}), config_path=str(c)
    )
    x = config.load_user("world", config_path=str(c))
    assert x == {"ThisIsOption": "hello"}

    config.update_config(
        "world", T.cast(T.Any, {"ThisIsOption": "world2"}), config_path=str(c)
    )
    x = config.load_user("world", config_path=str(c))
    assert x == {"ThisIsOption": "world2"}


def test_load_user(tmpdir: py.path.local):
    c = tmpdir.join("empty_config.ini")
    config.update_config(
        "world", T.cast(T.Any, {"ThisIsOption": "hello"}), config_path=str(c)
    )
    x = config.load_user("hello", config_path=str(c))
    assert x is None
    x = config.load_user("world", config_path=str(c))
    assert x == {"ThisIsOption": "hello"}


def test_remove(tmpdir: py.path.local):
    c = tmpdir.join("empty_config.ini")
    config.update_config(
        "world", T.cast(T.Any, {"ThisIsOption": "hello"}), config_path=str(c)
    )
    config.remove_config("world", config_path=str(c))
    u = config.load_user("world", config_path=str(c))
    assert u is None
    x = config.list_all_users(config_path=str(c))
    assert not x


def test_save_list_remove_organizations(tmpdir: py.path.local):
    c = str(tmpdir.join("config.ini"))
    for profile_name in ["me", "other"]:
        config.update_config(
            profile_name,
            T.cast(T.Any, {"user_upload_token": f"{profile_name}_token"}),
            config_path=c,
        )

    config.save_organization("me", "work", "1234567890", config_path=c)
    config.save_organization("me", "Work", "2222222222", config_path=c)

    # One line per name in the profile's own section, not a section of its own,
    # which list_all_users would take for a profile
    users = config.list_all_users(config_path=c)
    assert set(users) == {"me", "other"}
    with open(c) as fp:
        text = fp.read()
    assert "MAPOrganization.work = 1234567890\n" in text
    assert text.index("[me]") < text.index("MAPOrganization.work")
    assert text.index("MAPOrganization.work") < text.index("[other]")
    # Case-sensitive, like profile names
    assert config.list_organizations(users["me"]) == {
        "work": "1234567890",
        "Work": "2222222222",
    }
    assert config.list_organizations(users["other"]) == {}

    assert config.remove_organization("me", "work", config_path=c)
    assert not config.remove_organization("me", "work", config_path=c)
    assert not config.remove_organization("nobody", "Work", config_path=c)
    assert config.load_user("me", config_path=c) == {
        "user_upload_token": "me_token",
        "MAPOrganization.Work": "2222222222",
    }


def _write_profile(config_path: str, token: str) -> None:
    config.update_config(
        "me", T.cast(T.Any, {"user_upload_token": token}), config_path=config_path
    )


def test_write_config_replaces_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    c = tmp_path.joinpath("config.ini")
    _write_profile(str(c), "first")

    replaced: list[tuple[str, str]] = []
    os_replace = os.replace

    def _replace(src: str, dst: str) -> None:
        replaced.append((src, dst))
        os_replace(src, dst)

    monkeypatch.setattr(config.os, "replace", _replace)
    _write_profile(str(c), "second")

    # Written to a temporary file in the same folder, which replaced the config
    [(src, dst)] = replaced
    assert os.path.dirname(src) == os.path.dirname(os.path.realpath(c))
    assert dst == os.path.realpath(c)
    assert config.load_user("me", config_path=str(c)) == {"user_upload_token": "second"}
    assert [p.name for p in tmp_path.iterdir()] == ["config.ini"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_write_config_keeps_the_file_mode(tmp_path: Path):
    c = tmp_path.joinpath("config.ini")
    _write_profile(str(c), "first")
    for mode in [0o644, 0o640]:
        c.chmod(mode)
        _write_profile(str(c), "second")
        assert stat.S_IMODE(c.stat().st_mode) == mode


def test_write_config_through_a_symlink(tmp_path: Path):
    target = tmp_path.joinpath("dotfiles", "config.ini")
    target.parent.mkdir()
    _write_profile(str(target), "first")
    link = tmp_path.joinpath("configs", "config.ini")
    link.parent.mkdir()
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Unable to create symlinks")

    _write_profile(str(link), "second")

    assert link.is_symlink()
    assert config.load_user("me", config_path=str(target)) == {
        "user_upload_token": "second"
    }


@pytest.mark.parametrize(
    "error",
    [
        # On Windows, when another process has the config open
        PermissionError(errno.EACCES, "Access is denied"),
        # A config file mounted into a container
        OSError(errno.EBUSY, "Device or resource busy"),
    ],
)
def test_write_config_in_place_when_unable_to_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError
):
    c = tmp_path.joinpath("config.ini")
    _write_profile(str(c), "first")

    def _replace(src: str, dst: str) -> None:
        raise error

    monkeypatch.setattr(config.os, "replace", _replace)
    _write_profile(str(c), "second")

    assert config.load_user("me", config_path=str(c)) == {"user_upload_token": "second"}
    assert [p.name for p in tmp_path.iterdir()] == ["config.ini"]


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="POSIX folder permissions, which root ignores",
)
def test_write_config_in_a_folder_without_write_permission(tmp_path: Path):
    folder = tmp_path.joinpath("configs")
    folder.mkdir()
    c = folder.joinpath("config.ini")
    _write_profile(str(c), "first")
    folder.chmod(0o555)
    try:
        _write_profile(str(c), "second")
    finally:
        folder.chmod(0o755)

    assert config.load_user("me", config_path=str(c)) == {"user_upload_token": "second"}
    assert [p.name for p in folder.iterdir()] == ["config.ini"]


def test_write_config_failure_leaves_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    c = tmp_path.joinpath("config.ini")
    _write_profile(str(c), "first")
    before = c.read_text()

    def _fsync(fd: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(config.os, "fsync", _fsync)
    with pytest.raises(OSError, match="No space left"):
        _write_profile(str(c), "second")

    assert c.read_text() == before
    assert [p.name for p in tmp_path.iterdir()] == ["config.ini"]
