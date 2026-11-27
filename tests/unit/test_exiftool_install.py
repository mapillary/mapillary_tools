# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
mapillary_tools installs the latest ExifTool release the first time it needs
one, once for each version of mapillary_tools
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
import requests
from mapillary_tools import constants, exceptions, exiftool_install, types, VERSION
from mapillary_tools.commands import install_exiftool as install_exiftool_command
from mapillary_tools.geotag import (
    geotag_images_from_exiftool,
    geotag_videos_from_exiftool,
)


# Before the tests replace them
_RUN_VERSION = exiftool_install._run_version
_WHICH = shutil.which


def _perl_distribution(version: str, files: dict[str, bytes] | None = None) -> bytes:
    if files is None:
        files = {
            "exiftool": f'#!/usr/bin/env perl\nprint "{version}\\n";\n'.encode(),
            "lib/Image/ExifTool.pm": b"1;\n",
            "README": b"ExifTool\n",
            "html/index.html": b"<html></html>\n",
            "t/ExifTool.t": b"\n",
        }
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(f"Image-ExifTool-{version}/{name}")
            info.size = len(content)
            info.mode = 0o755 if name == "exiftool" else 0o644
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _windows_executable(version: str, bits: int) -> bytes:
    top = f"exiftool-{version}_{bits}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo(f"{top}/"), b"")
        zf.writestr(f"{top}/exiftool(-k).exe", b"MZ exiftool")
        zf.writestr(f"{top}/exiftool_files/perl.exe", b"MZ perl")
        zf.writestr(f"{top}/exiftool_files/lib/Image/ExifTool.pm", b"1;\n")
        zf.writestr(f"{top}/README.txt", b"ExifTool\n")
    return buf.getvalue()


class _Response:
    def __init__(self, url: str, content: bytes | None):
        self.url = url
        self.content = content

    @property
    def text(self) -> str:
        assert self.content is not None
        return self.content.decode("utf-8")

    def raise_for_status(self) -> None:
        if self.content is None:
            raise requests.HTTPError(f"404 Client Error: Not Found for url: {self.url}")

    def iter_content(self, chunk_size: int = 1):
        assert self.content is not None
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args) -> None:
        pass


class _ExifToolOrg:
    """
    Stands in for exiftool.org and SourceForge, which serve the files of the
    latest ExifTool release
    """

    def __init__(self, version: str):
        self.requests: list[str] = []
        self.files: dict[str, bytes] = {}
        self.checksums: dict[str, str] = {}
        self.release(version)

    def release(self, version: str) -> None:
        self.version = version
        self.files = {}
        self.checksums = {}
        self.set_file(f"Image-ExifTool-{version}.tar.gz", _perl_distribution(version))
        self.set_file(f"exiftool-{version}_64.zip", _windows_executable(version, 64))
        self.set_file(f"exiftool-{version}_32.zip", _windows_executable(version, 32))

    def set_file(self, filename: str, content: bytes) -> None:
        self.files[filename] = content
        self.checksums[filename] = hashlib.sha256(content).hexdigest()

    def get(self, url: str, **kwargs) -> _Response:
        self.requests.append(url)
        if url == exiftool_install.VERSION_URL:
            return _Response(url, f"{self.version}\n".encode())
        if url == exiftool_install.CHECKSUMS_URL:
            lines = [f"SHA2-256({name})= {c}" for name, c in self.checksums.items()]
            lines += [f"MD5 ({name}) = 0123456789abcdef" for name in self.checksums]
            return _Response(url, "\n".join(lines).encode())
        for filename, content in self.files.items():
            if url == exiftool_install.DOWNLOAD_URL.format(filename=filename):
                return _Response(url, content)
        return _Response(url, None)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    server = _ExifToolOrg("13.64")
    monkeypatch.setattr(exiftool_install.http, "Session", lambda: server)
    monkeypatch.setattr(constants, "EXIFTOOL_INSTALL_DIR", str(tmp_path / "exiftool"))
    monkeypatch.setattr(constants, "EXIFTOOL_PATH", None)
    monkeypatch.setattr(constants, "EXIFTOOL_AUTO_INSTALL", True)
    monkeypatch.setattr(exiftool_install, "_is_windows", lambda: False)
    monkeypatch.setattr(exiftool_install.shutil, "which", {"perl": "perl"}.get)
    # What the ExifTool installed prints: the version of the latest release
    monkeypatch.setattr(exiftool_install, "_run_version", lambda _: server.version)
    exiftool_install.find_exiftool.cache_clear()
    yield server
    exiftool_install.find_exiftool.cache_clear()


def _install_dir() -> Path:
    return Path(constants.EXIFTOOL_INSTALL_DIR)


def _install_folder() -> Path:
    return _install_dir() / f"mapillary_tools-{VERSION}"


def _files(folder: Path) -> list[str]:
    return sorted(
        p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()
    )


def test_install_perl_distribution(server: _ExifToolOrg):
    executable = exiftool_install.install_exiftool()

    assert executable == _install_folder() / "exiftool"
    # Only what ExifTool runs with, without the docs and the tests
    assert _files(_install_folder()) == ["README", "exiftool", "lib/Image/ExifTool.pm"]
    if sys.platform != "win32":
        assert os.access(executable, os.X_OK)
    assert server.requests == [
        exiftool_install.VERSION_URL,
        exiftool_install.CHECKSUMS_URL,
        exiftool_install.DOWNLOAD_URL.format(filename="Image-ExifTool-13.64.tar.gz"),
    ]
    # No download or temporary folder left
    assert [p.name for p in _install_dir().iterdir()] == [_install_folder().name]


@pytest.mark.parametrize("machine, bits", [("AMD64", 64), ("ARM64", 64), ("x86", 32)])
def test_install_windows_executable(
    server: _ExifToolOrg, monkeypatch: pytest.MonkeyPatch, machine: str, bits: int
):
    monkeypatch.setattr(exiftool_install, "_is_windows", lambda: True)
    monkeypatch.setattr(exiftool_install.platform, "machine", lambda: machine)
    # Perl comes with the Windows executable
    monkeypatch.setattr(exiftool_install.shutil, "which", lambda _: None)

    executable = exiftool_install.install_exiftool()

    # exiftool(-k).exe runs as exiftool.exe on the command line
    assert executable == _install_folder() / "exiftool.exe"
    assert _files(_install_folder()) == [
        "README.txt",
        "exiftool.exe",
        "exiftool_files/lib/Image/ExifTool.pm",
        "exiftool_files/perl.exe",
    ]
    assert server.requests[-1] == exiftool_install.DOWNLOAD_URL.format(
        filename=f"exiftool-13.64_{bits}.zip"
    )


def test_install_once_per_version(server: _ExifToolOrg):
    executable = exiftool_install.install_exiftool()
    server.requests.clear()
    server.release("13.65")

    assert exiftool_install.install_exiftool() == executable
    assert exiftool_install.find_exiftool() == str(executable)
    assert server.requests == []
    assert "13.64" in executable.read_text()


def test_force_installs_latest(server: _ExifToolOrg):
    executable = exiftool_install.install_exiftool()
    server.release("13.65")

    assert exiftool_install.install_exiftool(force=True) == executable
    assert "13.65" in executable.read_text()
    assert [p.name for p in _install_dir().iterdir()] == [_install_folder().name]


def test_remove_installs_of_other_versions(server: _ExifToolOrg):
    older = _install_dir() / "mapillary_tools-0.14.7"
    (older / "lib").mkdir(parents=True)
    (older / "exiftool").write_text("old")
    (_install_dir() / ".trash-0123").mkdir()
    (_install_dir() / "other").mkdir()

    exiftool_install.install_exiftool()

    assert sorted(p.name for p in _install_dir().iterdir()) == sorted(
        [_install_folder().name, "other"]
    )


def _assert_nothing_installed() -> None:
    assert exiftool_install.installed_exiftool() is None
    if _install_dir().exists():
        assert list(_install_dir().iterdir()) == []


def test_checksum_mismatch(server: _ExifToolOrg):
    server.checksums["Image-ExifTool-13.64.tar.gz"] = "0" * 64

    with pytest.raises(exceptions.MapillaryExiftoolInstallError, match="checksum"):
        exiftool_install.install_exiftool()
    _assert_nothing_installed()


def test_checksum_not_published(server: _ExifToolOrg):
    server.checksums.clear()

    with pytest.raises(exceptions.MapillaryExiftoolInstallError, match="checksum"):
        exiftool_install.install_exiftool()
    assert server.requests == [
        exiftool_install.VERSION_URL,
        exiftool_install.CHECKSUMS_URL,
    ]
    _assert_nothing_installed()


def test_unexpected_version(server: _ExifToolOrg):
    server.version = "<html>Not Found</html>"

    with pytest.raises(exceptions.MapillaryExiftoolInstallError, match="version"):
        exiftool_install.install_exiftool()
    assert server.requests == [exiftool_install.VERSION_URL]


def test_download_fails(server: _ExifToolOrg):
    server.files.clear()

    with pytest.raises(exceptions.MapillaryExiftoolInstallError, match="download"):
        exiftool_install.install_exiftool()
    _assert_nothing_installed()


def test_installed_exiftool_fails_to_run(
    server: _ExifToolOrg, monkeypatch: pytest.MonkeyPatch
):
    def _fail(executable: Path) -> str:
        raise exceptions.MapillaryExiftoolInstallError("Can't locate Image/ExifTool.pm")

    monkeypatch.setattr(exiftool_install, "_run_version", _fail)

    with pytest.raises(exceptions.MapillaryExiftoolInstallError):
        exiftool_install.install_exiftool()
    _assert_nothing_installed()


def test_installed_exiftool_prints_another_version(
    server: _ExifToolOrg, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(exiftool_install, "_run_version", lambda _: "12.40")

    with pytest.raises(exceptions.MapillaryExiftoolInstallError, match="12.40"):
        exiftool_install.install_exiftool()
    _assert_nothing_installed()


def test_file_outside_of_the_install_folder(server: _ExifToolOrg, tmp_path: Path):
    server.set_file(
        "Image-ExifTool-13.64.tar.gz",
        _perl_distribution(
            "13.64", {"exiftool": b"", "lib/../../../evil": b"", "lib/a.pm": b""}
        ),
    )

    with pytest.raises(exceptions.MapillaryExiftoolInstallError, match="Unexpected"):
        exiftool_install.install_exiftool()
    assert not list(tmp_path.rglob("evil"))
    _assert_nothing_installed()


def test_no_executable_in_release(server: _ExifToolOrg):
    server.set_file(
        "Image-ExifTool-13.64.tar.gz",
        _perl_distribution("13.64", {"lib/Image/ExifTool.pm": b"1;\n"}),
    )

    with pytest.raises(exceptions.MapillaryExiftoolInstallError, match="No exiftool"):
        exiftool_install.install_exiftool()
    _assert_nothing_installed()


def test_no_perl(server: _ExifToolOrg, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(exiftool_install.shutil, "which", lambda _: None)

    with pytest.raises(exceptions.MapillaryExiftoolInstallError, match="Perl"):
        exiftool_install.install_exiftool()
    assert server.requests == []


def test_find_installs_exiftool(server: _ExifToolOrg):
    assert exiftool_install.find_exiftool() == str(_install_folder() / "exiftool")


def test_find_exiftool_path_set(server: _ExifToolOrg, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(constants, "EXIFTOOL_PATH", "/opt/exiftool/exiftool")
    exiftool_install.install_exiftool()
    server.requests.clear()

    assert exiftool_install.find_exiftool() == "/opt/exiftool/exiftool"
    assert server.requests == []


def test_find_without_auto_install(
    server: _ExifToolOrg, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(constants, "EXIFTOOL_AUTO_INSTALL", False)

    assert exiftool_install.find_exiftool() == "exiftool"
    assert server.requests == []


def test_find_installed_without_auto_install(
    server: _ExifToolOrg, monkeypatch: pytest.MonkeyPatch
):
    # As with the install_exiftool command
    executable = exiftool_install.install_exiftool()
    monkeypatch.setattr(constants, "EXIFTOOL_AUTO_INSTALL", False)

    assert exiftool_install.find_exiftool() == str(executable)


def test_find_falls_back_to_path(
    server: _ExifToolOrg, caplog: pytest.LogCaptureFixture
):
    server.files.clear()

    with caplog.at_level(logging.WARNING):
        assert exiftool_install.find_exiftool() == "exiftool"
    assert "Failed to install ExifTool" in caplog.text
    # Not tried again in the same run
    server.requests.clear()
    assert exiftool_install.find_exiftool() == "exiftool"
    assert server.requests == []


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("perl") is None,
    reason="runs the Perl distribution",
)
def test_install_runs_perl_distribution(
    server: _ExifToolOrg, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(exiftool_install, "_run_version", _RUN_VERSION)
    monkeypatch.setattr(exiftool_install.shutil, "which", _WHICH)

    executable = exiftool_install.install_exiftool()

    assert exiftool_install._run_version(executable) == "13.64"


def test_install_exiftool_command(
    server: _ExifToolOrg, capsys: pytest.CaptureFixture[str]
):
    install_exiftool_command.Command().run({"force": False})

    assert capsys.readouterr().out == f"{_install_folder() / 'exiftool'}\n"


class _ExiftoolNotFound:
    def __init__(self, exiftool_executable: str = "exiftool", **kwargs):
        self.exiftool_executable = exiftool_executable
        _ExiftoolNotFound.executables.append(exiftool_executable)

    executables: list[str] = []

    def _build_args_read_stdin(self) -> list[str]:
        return [self.exiftool_executable]

    def extract_xml(self, paths) -> str:
        raise FileNotFoundError(self.exiftool_executable)


@pytest.mark.parametrize(
    "module", [geotag_images_from_exiftool, geotag_videos_from_exiftool]
)
def test_geotag_runs_exiftool_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, module
):
    monkeypatch.setattr(
        exiftool_install, "find_exiftool", lambda: "/installed/exiftool"
    )
    monkeypatch.setattr(module, "ExiftoolRunner", _ExiftoolNotFound)
    _ExiftoolNotFound.executables = []
    path = tmp_path / "file.mp4"
    path.write_bytes(b"")

    if module is geotag_images_from_exiftool:
        results = module.GeotagImagesFromExifToolRunner()._generate_image_extractors(
            [path]
        )
    else:
        results = module.GeotagVideosFromExifToolRunner()._generate_video_extractors(
            [path]
        )

    assert _ExiftoolNotFound.executables == ["/installed/exiftool"]
    assert len(results) == 1
    assert isinstance(results[0], types.ErrorMetadata)
    assert isinstance(results[0].error, exceptions.MapillaryExiftoolNotFoundError)
