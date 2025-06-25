# pyre-ignore-all-errors[5, 24]
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import typing as T
from pathlib import Path

LOG = logging.getLogger(__name__)
_MAX_STDERR_LENGTH = 2048


class StreamTag(T.TypedDict):
    creation_time: str
    language: str


class Stream(T.TypedDict):
    codec_name: str
    codec_tag_string: str
    codec_type: str
    duration: str
    height: int
    index: int
    tags: StreamTag
    width: int
    r_frame_rate: str
    avg_frame_rate: str
    nb_frames: str


class ProbeOutput(T.TypedDict):
    streams: list[Stream]


class FFmpegNotFoundError(Exception):
    pass


def _truncate_begin(s: str) -> str:
    if _MAX_STDERR_LENGTH < len(s):
        return "..." + s[-_MAX_STDERR_LENGTH:]
    else:
        return s


def _truncate_end(s: str) -> str:
    if _MAX_STDERR_LENGTH < len(s):
        return s[:_MAX_STDERR_LENGTH] + "..."
    else:
        return s


class FFmpegCalledProcessError(Exception):
    def __init__(self, ex: subprocess.CalledProcessError):
        self.inner_ex = ex

    def __str__(self) -> str:
        msg = str(self.inner_ex)
        if self.inner_ex.stderr is not None:
            try:
                stderr = self.inner_ex.stderr.decode("utf-8")
            except UnicodeDecodeError:
                stderr = str(self.inner_ex.stderr)
            msg += f"\nSTDERR: {_truncate_begin(stderr)}"
        return msg


class FFMPEG:
    FRAME_EXT = ".jpg"

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
        stderr: int | None = None,
    ) -> None:
        """
        Initialize FFMPEG wrapper with paths to ffmpeg and ffprobe binaries.

        Args:
            ffmpeg_path: Path to ffmpeg binary executable
            ffprobe_path: Path to ffprobe binary executable
            stderr: Parameter passed to subprocess.run to control stderr capture.
                   Use subprocess.PIPE to capture stderr, None to inherit from parent
        """
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.stderr = stderr

    def probe_format_and_streams(self, video_path: Path) -> ProbeOutput:
        """
        Probe video file to extract format and stream information using ffprobe.

        Args:
            video_path: Path to the video file to probe

        Returns:
            Dictionary containing streams and format information from ffprobe

        Raises:
            FFmpegNotFoundError: If ffprobe binary is not found
            FFmpegCalledProcessError: If ffprobe command fails
            RuntimeError: If output cannot be decoded or parsed as JSON
        """
        cmd: list[str] = [
            "-hide_banner",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]
        return T.cast(ProbeOutput, self._run_ffprobe_json(cmd))

    def extract_frames_by_interval(
        self,
        video_path: Path,
        sample_dir: Path,
        sample_interval: float,
        stream_specifier: int | str = "v",
    ) -> None:
        """
        Extract frames from video at regular time intervals using fps filter.

        Args:
            video_path: Path to input video file
            sample_dir: Directory where extracted frame images will be saved
            sample_interval: Time interval between extracted frames in seconds
            stream_specifier: Stream specifier to target specific stream(s).
                              Can be an integer (stream index) or "v" (all video streams)
                              See https://ffmpeg.org/ffmpeg.html#Stream-specifiers-1

        Raises:
            FFmpegNotFoundError: If ffmpeg binary is not found
            FFmpegCalledProcessError: If ffmpeg command fails
        """
        self._validate_stream_specifier(stream_specifier)

        sample_prefix = sample_dir.joinpath(video_path.stem)
        stream_selector = ["-map", f"0:{stream_specifier}"]
        output_template = f"{sample_prefix}_{stream_specifier}_%06d{self.FRAME_EXT}"

        cmd: list[str] = [
            # Global options should be specified first
            *["-hide_banner"],
            # Input 0
            *["-i", str(video_path)],
            # Select stream
            *stream_selector,
            # Filter videos
            *["-vf", f"fps=1/{sample_interval}"],
            # Video quality level (or the alias -q:v)
            # -q:v=1 is the best quality but larger image sizes
            # see https://stackoverflow.com/a/10234065
            # *["-qscale:v", "1", "-qmin", "1"],
            *["-qscale:v", "2"],
            # Output
            output_template,
        ]

        self.run_ffmpeg_non_interactive(cmd)

    @classmethod
    def generate_binary_search(cls, sorted_frame_indices: list[int]) -> str:
        """
        Generate a binary search expression for ffmpeg select filter.

        Creates an optimized filter expression that uses binary search logic
        to efficiently select specific frame numbers from a video stream.

        Args:
            sorted_frame_indices: List of frame numbers to select, must be sorted in ascending order

        Returns:
            FFmpeg filter expression string using binary search logic

        Examples:
            >>> FFMPEG.generate_binary_search([])
            '0'
            >>> FFMPEG.generate_binary_search([1])
            'eq(n\\\\,1)'
            >>> FFMPEG.generate_binary_search([1, 2])
            'if(lt(n\\\\,2)\\\\,eq(n\\\\,1)\\\\,eq(n\\\\,2))'
            >>> FFMPEG.generate_binary_search([1, 2, 3])
            'if(lt(n\\\\,2)\\\\,eq(n\\\\,1)\\\\,if(lt(n\\\\,3)\\\\,eq(n\\\\,2)\\\\,eq(n\\\\,3)))'
        """

        length = len(sorted_frame_indices)

        if length == 0:
            return "0"

        if length == 1:
            return f"eq(n\\,{sorted_frame_indices[0]})"

        middle_idx = length // 2
        left = cls.generate_binary_search(sorted_frame_indices[:middle_idx])
        right = cls.generate_binary_search(sorted_frame_indices[middle_idx:])

        return f"if(lt(n\\,{sorted_frame_indices[middle_idx]})\\,{left}\\,{right})"

    def extract_specified_frames(
        self,
        video_path: Path,
        sample_dir: Path,
        frame_indices: set[int],
        stream_specifier: int | str = "v",
    ) -> None:
        """
        Extract specific frames from video by frame number using select filter.

        Uses a binary search filter expression to efficiently select only the
        specified frame numbers from the video stream.

        Args:
            video_path: Path to input video file
            sample_dir: Directory where extracted frame images will be saved
            frame_indices: Set of specific frame numbers to extract (0-based)
            stream_specifier: Stream specifier to target specific stream(s).
                              Can be an integer (stream index) or "v" (all video streams)
                              See https://ffmpeg.org/ffmpeg.html#Stream-specifiers-1

        Raises:
            FFmpegNotFoundError: If ffmpeg binary is not found
            FFmpegCalledProcessError: If ffmpeg command fails

        Note:
            Frame indices are 0-based but ffmpeg output files are numbered starting from 1.
            Creates temporary filter script file on Windows to avoid command line length limits.
        """

        self._validate_stream_specifier(stream_specifier)

        if not frame_indices:
            return

        sample_prefix = sample_dir.joinpath(video_path.stem)
        stream_selector = ["-map", f"0:{stream_specifier}"]
        output_template = f"{sample_prefix}_{stream_specifier}_%06d{self.FRAME_EXT}"

        eqs = self.generate_binary_search(sorted(frame_indices))

        # https://github.com/mapillary/mapillary_tools/issues/503
        if sys.platform in ["win32"]:
            delete = False
        else:
            delete = True

        # Write the select filter to a temp file because:
        # The select filter could be large and
        # the maximum command line length for the CreateProcess function is 32767 characters
        # https://devblogs.microsoft.com/oldnewthing/20031210-00/?p=41553
        with tempfile.NamedTemporaryFile(mode="w+", delete=delete) as select_file:
            try:
                select_file.write(f"select={eqs}")
                select_file.flush()
                # If not close, error "The process cannot access the file because it is being used by another process"
                if not delete:
                    select_file.close()
                cmd: list[str] = [
                    # Global options should be specified first
                    *["-hide_banner"],
                    # Input 0
                    *["-i", str(video_path)],
                    # Select stream
                    *stream_selector,
                    # Filter videos
                    *[
                        *["-filter_script:v", select_file.name],
                        # Each frame is passed with its timestamp from the demuxer to the muxer
                        *["-vsync", "0"],
                        # vsync is deprecated by fps_mode,
                        # but fps_mode is not avaliable on some older versions ;(
                        # *[f"-fps_mode:{stream_specifier}", "passthrough"],
                        # Set the number of video frames to output (this is an optimization to let ffmpeg stop early)
                        *["-frames:v", str(len(frame_indices))],
                        # Disabled because it doesn't always name the sample images as expected
                        # For example "select(n\,1)" we expected the first sample to be IMG_001.JPG
                        # but it could be IMG_005.JPG
                        # https://www.ffmpeg.org/ffmpeg-formats.html#Options-21
                        # If set to 1, expand the filename with pts from pkt->pts. Default value is 0.
                        # *["-frame_pts", "1"],
                    ],
                    # Video quality level (or the alias -q:v)
                    # -q:v=1 is the best quality but larger image sizes
                    # see https://stackoverflow.com/a/10234065
                    # *["-qscale:v", "1", "-qmin", "1"],
                    *["-qscale:v", "2"],
                    # output
                    output_template,
                ]
                self.run_ffmpeg_non_interactive(cmd)
            finally:
                if not delete:
                    try:
                        os.remove(select_file.name)
                    except FileNotFoundError:
                        pass

    @classmethod
    def sort_selected_samples(
        cls,
        sample_dir: Path,
        video_path: Path,
        selected_stream_specifiers: list[int | str] | None = None,
    ) -> list[tuple[int, list[Path | None]]]:
        """
        Group extracted frame samples by frame index across multiple streams.

        Groups frames so that the Nth group contains all frames from the selected
        streams at frame index N, allowing synchronized access to multi-stream frames.

        Args:
            sample_dir: Directory containing extracted frame files
            video_path: Original video file path (used to match frame filenames)
            selected_stream_specifiers: List of stream specifiers to include in output.
                                       Can contain integers (stream indices) or "v" (all video streams).
                                       If None, defaults to ["v"]

        Returns:
            List of tuples where each tuple contains:
            - frame_idx (int): The frame index
            - sample_paths (list[Path | None]): Paths to frame files from each selected stream,
              or None if no frame exists for that stream at this index

        Note:
            Output is sorted by frame index in ascending order.
        """
        if selected_stream_specifiers is None:
            selected_stream_specifiers = ["v"]

        for stream_specifier in selected_stream_specifiers:
            cls._validate_stream_specifier(stream_specifier)

        stream_samples: dict[int, list[tuple[str, Path]]] = {}
        for stream_specifier, frame_idx, sample_path in cls.iterate_samples(
            sample_dir, video_path
        ):
            stream_samples.setdefault(frame_idx, []).append(
                (str(stream_specifier), sample_path)
            )

        selected: list[tuple[int, list[Path | None]]] = []
        for frame_idx in sorted(stream_samples.keys()):
            indexed_by_specifier = {
                specifier: sample_path
                for specifier, sample_path in stream_samples[frame_idx]
            }
            selected_sample_paths = [
                indexed_by_specifier.get(str(specifier))
                for specifier in selected_stream_specifiers
            ]
            selected.append((frame_idx, selected_sample_paths))
        return selected

    @classmethod
    def iterate_samples(
        cls, sample_dir: Path, video_path: Path
    ) -> T.Generator[tuple[str, int, Path], None, None]:
        """
        Iterate over all extracted frame samples in a directory.

        Searches for frame files matching the expected naming pattern and yields
        information about each frame including stream specifier, frame index, and file path.

        Args:
            sample_dir: Directory containing extracted frame files
            video_path: Original video file path (used to match frame filenames)

        Yields:
            Tuple containing:
            - stream_specifier (str): Stream specifier (number or "v")
            - frame_idx (int): Frame index (0-based or 1-based depending on extraction method)
            - sample_path (Path): Path to the frame image file

        Note:
            Expected filename pattern: {video_stem}_{stream_specifier}_{frame_idx:06d}.jpg
            where stream_specifier can be a number or "v" for video streams.
        """
        sample_basename_pattern = re.compile(
            rf"""
            ^{re.escape(video_path.stem)}  # Match the video stem
            _(?P<stream_specifier>\d+|v)   # Stream specifier can be a number or "v"
            _(?P<frame_idx>\d+)$           # Frame index, can be 0-padded
            """,
            re.X,
        )
        for sample_path in sample_dir.iterdir():
            result = cls._extract_stream_frame_idx(
                sample_path.name, sample_basename_pattern
            )
            if result is not None:
                stream_specifier, frame_idx = result
                yield (stream_specifier, frame_idx, sample_path)

    def run_ffmpeg_non_interactive(self, cmd: list[str]) -> None:
        """
        Execute ffmpeg command in non-interactive mode.

        Runs ffmpeg with the given command arguments, automatically adding
        the -nostdin flag to prevent interactive prompts.

        Args:
            cmd: List of command line arguments to pass to ffmpeg

        Raises:
            FFmpegNotFoundError: If ffmpeg binary is not found
            FFmpegCalledProcessError: If ffmpeg command fails
        """
        full_cmd: list[str] = [self.ffmpeg_path, "-nostdin", *cmd]
        LOG.info(f"Running ffmpeg: {' '.join(full_cmd)}")
        try:
            subprocess.run(full_cmd, check=True, stderr=self.stderr)
        except FileNotFoundError:
            raise FFmpegNotFoundError(
                f'The ffmpeg command "{self.ffmpeg_path}" not found'
            )
        except subprocess.CalledProcessError as ex:
            raise FFmpegCalledProcessError(ex) from ex

    @classmethod
    def _extract_stream_frame_idx(
        cls, sample_basename: str, pattern: T.Pattern[str]
    ) -> tuple[str, int] | None:
        """
        Extract stream specifier and frame index from sample basename

        Returns:
            If returning None, it means the basename does not match the pattern

        Examples:
            * basename GX010001_v_000000.jpg will extract ("v", 0)
            * basename GX010001_1_000002.jpg will extract ("1", 2)
        """
        image_no_ext, ext = os.path.splitext(sample_basename)
        if ext.lower() != cls.FRAME_EXT.lower():
            return None

        match = pattern.match(image_no_ext)
        if not match:
            return None

        stream_specifier = match.group("stream_specifier")

        # Convert 0-padded numbers to int
        # e.g. 000000 -> 0
        # e.g. 000001 -> 1
        frame_idx_str = match.group("frame_idx")
        frame_idx_str = frame_idx_str.lstrip("0") or "0"

        try:
            frame_idx = int(frame_idx_str)
        except ValueError:
            return None

        return stream_specifier, frame_idx

    def _run_ffprobe_json(self, cmd: list[str]) -> dict:
        full_cmd: list[str] = [self.ffprobe_path, "-print_format", "json", *cmd]
        LOG.info(f"Extracting video information: {' '.join(full_cmd)}")
        try:
            completed = subprocess.run(
                full_cmd, check=True, stdout=subprocess.PIPE, stderr=self.stderr
            )
        except FileNotFoundError:
            raise FFmpegNotFoundError(
                f'The ffprobe command "{self.ffprobe_path}" not found'
            )
        except subprocess.CalledProcessError as ex:
            raise FFmpegCalledProcessError(ex) from ex

        try:
            stdout = completed.stdout.decode("utf-8")
        except UnicodeDecodeError:
            raise RuntimeError(
                f"Error decoding ffprobe output as unicode: {_truncate_end(str(completed.stdout))}"
            )

        try:
            output = json.loads(stdout)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"Error JSON decoding ffprobe output: {_truncate_end(stdout)}"
            )

        # This check is for macOS:
        # ffprobe -hide_banner -print_format json not_exists
        # you will get exit code == 0 with the following stdout and stderr:
        # {
        # }
        # not_exists: No such file or directory
        if not output:
            raise RuntimeError(
                f"Empty JSON ffprobe output with STDERR: {_truncate_begin(str(completed.stderr))}"
            )

        return output

    @classmethod
    def _validate_stream_specifier(cls, stream_specifier: int | str) -> None:
        if isinstance(stream_specifier, str):
            if stream_specifier in ["v"]:
                pass
            else:
                try:
                    int(stream_specifier)
                except ValueError:
                    raise ValueError(f"Invalid stream specifier: {stream_specifier}")


class Probe:
    probe_output: ProbeOutput

    def __init__(self, probe_output: ProbeOutput) -> None:
        """
        Initialize Probe with ffprobe output data.

        Args:
            probe_output: Dictionary containing streams and format information from ffprobe
        """
        self.probe_output = probe_output

    def probe_video_start_time(self) -> datetime.datetime | None:
        """
        Determine the start time of the video by analyzing stream metadata.

        Searches for creation time and duration information in video streams first,
        then falls back to other stream types. Calculates start time as:
        creation_time - duration

        Returns:
            Video start time as datetime object, or None if cannot be determined

        Note:
            Prioritizes video streams with highest resolution when multiple exist.
        """
        streams = self.probe_output.get("streams", [])

        # Search start time from video streams
        video_streams = self.probe_video_streams()
        video_streams.sort(
            key=lambda s: s.get("width", 0) * s.get("height", 0), reverse=True
        )
        for stream in video_streams:
            start_time = self.extract_stream_start_time(stream)
            if start_time is not None:
                return start_time

        # Search start time from the other streams
        for stream in streams:
            if stream.get("codec_type") != "video":
                start_time = self.extract_stream_start_time(stream)
                if start_time is not None:
                    return start_time

        return None

    def probe_video_streams(self) -> list[Stream]:
        """
        Extract all video streams from the probe output.

        Returns:
            List of video stream dictionaries containing metadata like codec,
            dimensions, frame rate, etc.
        """
        streams = self.probe_output.get("streams", [])
        return [stream for stream in streams if stream.get("codec_type") == "video"]

    def probe_video_with_max_resolution(self) -> Stream | None:
        """
        Find the video stream with the highest resolution.

        Sorts all video streams by width × height and returns the one with
        the largest resolution.

        Returns:
            Stream dictionary for the highest resolution video stream,
            or None if no video streams exist
        """
        video_streams = self.probe_video_streams()
        video_streams.sort(
            key=lambda s: s.get("width", 0) * s.get("height", 0), reverse=True
        )
        if not video_streams:
            return None
        return video_streams[0]

    @classmethod
    def extract_stream_start_time(cls, stream: Stream) -> datetime.datetime | None:
        """
        Calculate the start time of a specific stream.

        Determines start time by subtracting stream duration from creation time:
        start_time = creation_time - duration

        Args:
            stream: Stream dictionary containing metadata including tags and duration

        Returns:
            Stream start time as datetime object, or None if required metadata is missing

        Note:
            Handles multiple datetime formats including ISO format and custom patterns.
        """
        duration_str = stream.get("duration")
        LOG.debug("Extracted video duration: %s", duration_str)
        if duration_str is None:
            return None
        duration = float(duration_str)

        creation_time_str = stream.get("tags", {}).get("creation_time")
        LOG.debug("Extracted video creation time: %s", creation_time_str)
        if creation_time_str is None:
            return None
        try:
            creation_time = datetime.datetime.fromisoformat(creation_time_str)
        except ValueError:
            creation_time = datetime.datetime.strptime(
                creation_time_str, "%Y-%m-%dT%H:%M:%S.%f%z"
            )
        return creation_time - datetime.timedelta(seconds=duration)
