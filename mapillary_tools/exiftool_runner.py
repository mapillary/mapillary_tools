from __future__ import annotations

import platform
import shutil
import subprocess
import typing as T
from pathlib import Path


class ExiftoolRunner:
    """
    Wrapper around ExifTool to run it in a subprocess
    """

    def __init__(self, exiftool_path: str | None = None, recursive: bool = False):
        if exiftool_path is None:
            exiftool_path = self._search_preferred_exiftool_path()
        self.exiftool_path = exiftool_path
        self.recursive = recursive

    def _search_preferred_exiftool_path(self) -> str:
        system = platform.system()

        if system and system.lower() == "windows":
            exiftool_paths = ["exiftool.exe", "exiftool"]
        else:
            exiftool_paths = ["exiftool", "exiftool.exe"]

        for path in exiftool_paths:
            full_path = shutil.which(path)
            if full_path:
                return path

        # Always return the prefered one, even if it is not found,
        # and let the subprocess.run figure out the error later
        return exiftool_paths[0]

    def _build_args_read_stdin(self) -> list[str]:
        args: list[str] = [
            self.exiftool_path,
            "-fast",
            "-q",
            "-n",  # Disable print conversion
            "-X",  # XML output
            "-ee",
            *["-api", "LargeFileSupport=1"],
            *["-charset", "filename=utf8"],
            *["-@", "-"],
        ]

        if self.recursive:
            args.append("-r")

        return args

    def extract_xml(self, paths: T.Sequence[Path]) -> str:
        if not paths:
            # ExifTool will show its full manual if no files are provided
            raise ValueError("No files provided to exiftool")

        # To handle non-latin1 filenames under Windows, we pass the path
        # via stdin. See https://exiftool.org/faq.html#Q18
        stdin = "\n".join([str(p.resolve()) for p in paths])

        args = self._build_args_read_stdin()

        # Raise FileNotFoundError here if self.exiftool_path not found
        process = subprocess.run(
            args,
            capture_output=True,
            text=True,
            input=stdin,
            encoding="utf-8",
            # Do not check exit status to allow some files not found
            # check=True,
        )

        return process.stdout
