# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Install ExifTool for mapillary_tools to read GPS with

Unless MAPILLARY_TOOLS_EXIFTOOL_PATH names the ExifTool to run, mapillary_tools
runs its own: the latest ExifTool release when it first needs one, downloaded
from exiftool.org into the user data folder. Each version of mapillary_tools
installs its own, and removes those of the other versions, so a new version of
mapillary_tools runs the ExifTool released by then, never an older one left by
the version before.

The release is installed as its author distributes it: the Perl distribution,
which runs with the Perl of the system, or on Windows the Windows executable.
Its SHA-256 checksum must match the one that exiftool.org publishes.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import typing as T
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import requests

from . import constants, exceptions, http, VERSION


LOG = logging.getLogger(__name__)

# The version number of the latest ExifTool release
VERSION_URL = "https://exiftool.org/ver.txt"
# The checksums of the files of the latest ExifTool release
CHECKSUMS_URL = "https://exiftool.org/checksums.txt"
# exiftool.org links the files of its releases to SourceForge
DOWNLOAD_URL = "https://sourceforge.net/projects/exiftool/files/{filename}/download"
# (connect, read) in seconds
REQUEST_TIMEOUT = (10, 60)
# In seconds, how long the ExifTool installed may take to print its version
VERIFY_TIMEOUT = 120

# The folder of the ExifTool that each version of mapillary_tools installed
_INSTALL_FOLDER_PREFIX = "mapillary_tools-"
# Folders of installations being removed
_TRASH_FOLDER_PREFIX = ".trash-"
_VERSION_PATTERN = re.compile(r"^\d+\.\d+$")
_CHECKSUM_PATTERN = re.compile(
    r"^SHA2-256\((?P<filename>[^)]+)\)=\s*(?P<checksum>[0-9a-fA-F]{64})\s*$",
    re.MULTILINE,
)


def _is_windows() -> bool:
    return sys.platform == "win32"


def install_folder() -> Path:
    """
    The folder where this version of mapillary_tools installs ExifTool
    """
    return Path(constants.EXIFTOOL_INSTALL_DIR).joinpath(
        f"{_INSTALL_FOLDER_PREFIX}{VERSION}"
    )


def executable_path(folder: Path) -> Path:
    return folder.joinpath("exiftool.exe" if _is_windows() else "exiftool")


def installed_exiftool() -> Path | None:
    """
    The ExifTool that this version of mapillary_tools installed, if it did
    """
    executable = executable_path(install_folder())
    if executable.is_file():
        return executable
    return None


@functools.lru_cache(maxsize=None)
def find_exiftool() -> str:
    """
    The ExifTool to run:

    1. MAPILLARY_TOOLS_EXIFTOOL_PATH, if it is set
    2. the ExifTool that this version of mapillary_tools installed, which it
       installs now if it has not yet, unless MAPILLARY_TOOLS_EXIFTOOL_AUTO_INSTALL
       is NO
    3. otherwise, or if it fails to install, the exiftool on the PATH
    """
    if constants.EXIFTOOL_PATH is not None:
        return constants.EXIFTOOL_PATH

    executable = installed_exiftool()
    if executable is not None:
        return str(executable)

    if constants.EXIFTOOL_AUTO_INSTALL:
        try:
            return str(install_exiftool())
        except exceptions.MapillaryExiftoolInstallError as ex:
            LOG.warning(
                "Failed to install ExifTool, so running the exiftool on the PATH: %s",
                ex,
            )

    return "exiftool"


def install_exiftool(force: bool = False) -> Path:
    """
    Install the latest ExifTool release for this version of mapillary_tools,
    unless it installed one already (with **force**, in any case), and return
    the executable.

    Raise MapillaryExiftoolInstallError if it fails.
    """
    folder = install_folder()

    if not force:
        executable = installed_exiftool()
        if executable is not None:
            LOG.info("ExifTool is installed already in %s", folder)
            return executable

    if not _is_windows() and shutil.which("perl") is None:
        raise exceptions.MapillaryExiftoolInstallError(
            "Perl is not found on the PATH, and ExifTool runs with Perl"
        )

    session = http.Session()
    # The debug logs would read the whole download
    session.disable_logging_response = True

    try:
        version = _fetch_latest_version(session)
        filename = archive_filename(version)
        checksum = _fetch_checksum(session, filename)

        folder.parent.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix=".tmp-", dir=folder.parent))
        try:
            LOG.info("Installing ExifTool %s in %s", version, folder)
            archive = workdir.joinpath(filename)
            _download(
                session, DOWNLOAD_URL.format(filename=filename), archive, checksum
            )
            staging = workdir.joinpath("exiftool")
            _extract(archive, staging)
            _verify(executable_path(staging), version)
            _move_into_place(staging, folder, replace=force)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    # Before OSError, which it derives from
    except requests.RequestException as ex:
        raise exceptions.MapillaryExiftoolInstallError(
            f"Failed to download ExifTool: {ex}"
        ) from ex
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as ex:
        raise exceptions.MapillaryExiftoolInstallError(
            f"Failed to install ExifTool: {ex}"
        ) from ex

    _remove_other_installs(folder)

    return executable_path(folder)


def archive_filename(version: str) -> str:
    """
    The file of the ExifTool release **version** for this platform

    >>> archive_filename("13.64") in ("Image-ExifTool-13.64.tar.gz", "exiftool-13.64_64.zip", "exiftool-13.64_32.zip")
    True
    """
    if _is_windows():
        # AMD64 or ARM64, which runs x64 executables
        bits = 64 if platform.machine().endswith("64") else 32
        return f"exiftool-{version}_{bits}.zip"
    else:
        return f"Image-ExifTool-{version}.tar.gz"


def _fetch_latest_version(session: requests.Session) -> str:
    resp = session.get(VERSION_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    version = resp.text.strip()
    if not _VERSION_PATTERN.match(version):
        raise exceptions.MapillaryExiftoolInstallError(
            f"Unexpected version {version[:100]!r} from {VERSION_URL}"
        )
    return version


def _fetch_checksum(session: requests.Session, filename: str) -> str:
    resp = session.get(CHECKSUMS_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    for match in _CHECKSUM_PATTERN.finditer(resp.text):
        if match.group("filename") == filename:
            return match.group("checksum").lower()
    raise exceptions.MapillaryExiftoolInstallError(
        f"No SHA-256 checksum of {filename} in {CHECKSUMS_URL}"
    )


def _download(session: requests.Session, url: str, path: Path, checksum: str) -> None:
    sha256 = hashlib.sha256()
    with session.get(url, timeout=REQUEST_TIMEOUT, stream=True) as resp:
        resp.raise_for_status()
        with path.open("wb") as fp:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                sha256.update(chunk)
                fp.write(chunk)

    if sha256.hexdigest() != checksum:
        raise exceptions.MapillaryExiftoolInstallError(
            f"The SHA-256 checksum of {path.name} is {sha256.hexdigest()}, but {CHECKSUMS_URL} gives {checksum}"
        )


def installed_relative_path(name: str) -> tuple[str, ...] | None:
    """
    Where the file **name** of a release archive is installed, relative to the
    install folder, or None if ExifTool does not run with it. The files are in
    a top folder, which is left out

    >>> installed_relative_path("Image-ExifTool-13.64/lib/Image/ExifTool.pm")
    ('lib', 'Image', 'ExifTool.pm')
    >>> installed_relative_path("Image-ExifTool-13.64/exiftool")
    ('exiftool',)
    >>> installed_relative_path("exiftool-13.64_64/exiftool(-k).exe")
    ('exiftool.exe',)
    >>> installed_relative_path("exiftool-13.64_64/exiftool_files/perl.exe")
    ('exiftool_files', 'perl.exe')
    >>> installed_relative_path("Image-ExifTool-13.64/html/index.html") is None
    True
    >>> installed_relative_path("exiftool-13.64_64/exiftool_files/../../evil.exe")
    Traceback (most recent call last):
    mapillary_tools.exceptions.MapillaryExiftoolInstallError: Unexpected file in the ExifTool release: 'exiftool-13.64_64/exiftool_files/../../evil.exe'
    """
    parts = PurePosixPath(name).parts
    relative = parts[1:]

    installed: tuple[str, ...]
    if relative in [("exiftool",), ("README",), ("README.txt",)]:
        installed = relative
    # The Windows executable runs as exiftool.exe on the command line
    elif relative == ("exiftool(-k).exe",):
        installed = ("exiftool.exe",)
    # The Perl modules, or the Perl that the Windows executable runs with
    elif 2 <= len(relative) and relative[0] in ["lib", "exiftool_files"]:
        installed = relative
    else:
        return None

    if any(part in ("/", "..") or "\\" in part or ":" in part for part in parts):
        raise exceptions.MapillaryExiftoolInstallError(
            f"Unexpected file in the ExifTool release: {name!r}"
        )

    return installed


def _extract(archive: Path, folder: Path) -> None:
    """
    Extract the files that ExifTool runs with from the release **archive** into
    **folder**
    """
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                relative = installed_relative_path(info.filename)
                if relative is not None:
                    with zf.open(info) as fp:
                        _write_file(folder.joinpath(*relative), fp)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf:
                # Neither links nor special files
                if not member.isfile():
                    continue
                relative = installed_relative_path(member.name)
                if relative is not None:
                    member_fp = tf.extractfile(member)
                    assert member_fp is not None, (
                        f"No content of the regular file {member.name}"
                    )
                    with member_fp:
                        _write_file(folder.joinpath(*relative), member_fp)

    executable = executable_path(folder)
    if not executable.is_file():
        raise exceptions.MapillaryExiftoolInstallError(
            f"No {executable.name} in {archive.name}"
        )
    if not _is_windows():
        executable.chmod(0o755)


def _write_file(path: Path, fp: T.IO[bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as output:
        shutil.copyfileobj(fp, output)


def _run_version(executable: Path) -> str:
    """
    The version that **executable** prints, as mapillary_tools runs it
    """
    try:
        process = subprocess.run(
            [str(executable), "-ver"],
            capture_output=True,
            text=True,
            timeout=VERIFY_TIMEOUT,
        )
    except subprocess.TimeoutExpired as ex:
        raise exceptions.MapillaryExiftoolInstallError(
            f"ExifTool did not print its version in {VERIFY_TIMEOUT} seconds"
        ) from ex

    if process.returncode != 0:
        raise exceptions.MapillaryExiftoolInstallError(
            f"ExifTool failed to print its version (exit code {process.returncode}): {process.stderr.strip()[-500:]}"
        )

    return process.stdout.strip()


def _verify(executable: Path, version: str) -> None:
    printed = _run_version(executable)
    if printed != version:
        raise exceptions.MapillaryExiftoolInstallError(
            f"ExifTool {version} printed version {printed[:100]!r}"
        )


def _move_into_place(staging: Path, folder: Path, replace: bool) -> None:
    if replace and folder.exists():
        if not _remove_install(folder):
            LOG.warning("Failed to replace the ExifTool installed in %s", folder)

    try:
        os.rename(staging, folder)
    except OSError:
        # Installed meanwhile, by another process of this version of mapillary_tools
        if executable_path(folder).is_file():
            return
        raise


def _remove_install(folder: Path) -> bool:
    """
    Remove the ExifTool installed in **folder**, unless it is running

    Moved away first, so that a folder half removed is never taken for an
    ExifTool installed: on Windows, a running ExifTool can be neither removed
    nor moved
    """
    trash = folder.with_name(f"{_TRASH_FOLDER_PREFIX}{uuid.uuid4().hex}")
    try:
        os.rename(folder, trash)
    except OSError as ex:
        LOG.debug("Failed to move %s to %s: %s", folder, trash, ex)
        return False
    shutil.rmtree(trash, ignore_errors=True)
    return True


def _remove_other_installs(folder: Path) -> None:
    """
    Remove the ExifTool installed by other versions of mapillary_tools
    """
    try:
        paths = list(folder.parent.iterdir())
    except OSError as ex:
        LOG.debug("Failed to list %s: %s", folder.parent, ex)
        return

    for path in paths:
        if path == folder or not path.is_dir():
            continue
        if path.name.startswith(_TRASH_FOLDER_PREFIX):
            shutil.rmtree(path, ignore_errors=True)
        elif path.name.startswith(_INSTALL_FOLDER_PREFIX):
            if _remove_install(path):
                LOG.debug("Removed the ExifTool installed in %s", path)
