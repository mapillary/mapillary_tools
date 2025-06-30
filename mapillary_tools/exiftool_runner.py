from __future__ import annotations

import subprocess
import typing as T
from pathlib import Path


class ExiftoolRunner:
    """
    Wrapper around ExifTool to run it in a subprocess
    """

    def __init__(self, exiftool_executable: str = "exiftool", recursive: bool = False):
        self.exiftool_executable = exiftool_executable
        self.recursive = recursive

    def _build_args_read_stdin(self) -> list[str]:
        args: list[str] = [
            self.exiftool_executable,
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
