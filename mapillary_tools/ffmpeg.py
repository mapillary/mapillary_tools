# pyre-ignore-all-errors[5, 24]

import datetime
import json
import logging
import os
import subprocess
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 8):
    from typing import TypedDict  # pylint: disable=no-name-in-module
else:
    from typing_extensions import TypedDict

LOG = logging.getLogger(__name__)
FRAME_EXT = ".jpg"


class StreamTag(TypedDict):
    creation_time: str
    language: str


class Stream(TypedDict):
    codec_name: str
    codec_tag_string: str
    codec_type: str
    duration: str
    height: int
    index: int
    tags: StreamTag
    width: int


class ProbeOutput(TypedDict):
    streams: T.List[Stream]


class FFmpegNotFoundError(Exception):
    pass


_MAX_STDERR_LENGTH = 2048


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
    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
        stderr: T.Optional[int] = None,
    ) -> None:
        """
        ffmpeg_path: path to ffmpeg binary
        ffprobe_path: path to ffprobe binary
        stderr: param passed to subprocess.run to control whether to capture stderr
        """
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.stderr = stderr

    def _run_ffprobe_json(self, cmd: T.List[str]) -> T.Dict:
        full_cmd = [self.ffprobe_path, "-print_format", "json", *cmd]
        LOG.info(f"Extracting video information: {' '.join(full_cmd)}")
        try:
            completed = subprocess.run(
                full_cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=self.stderr,
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

    def _run_ffmpeg(self, cmd: T.List[str]) -> None:
        full_cmd = [self.ffmpeg_path, *cmd]
        LOG.info(f"Extracting frames: {' '.join(full_cmd)}")
        try:
            subprocess.run(full_cmd, check=True, stderr=self.stderr)
        except FileNotFoundError:
            raise FFmpegNotFoundError(
                f'The ffmpeg command "{self.ffmpeg_path}" not found'
            )
        except subprocess.CalledProcessError as ex:
            raise FFmpegCalledProcessError(ex) from ex

    def probe_format_and_streams(self, video_path: Path) -> ProbeOutput:
        cmd = [
            "-hide_banner",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]
        return T.cast(ProbeOutput, self._run_ffprobe_json(cmd))

    def extract_frames(
        self,
        video_path: Path,
        sample_dir: Path,
        sample_interval: float,
    ) -> None:
        sample_prefix = sample_dir.joinpath(video_path.stem)
        cmd = [
            "-i",
            str(video_path),
            "-vf",
            f"fps=1/{sample_interval}",
            "-hide_banner",
            # video quality level
            "-qscale:v",
            "1",
            "-nostdin",
            f"{sample_prefix}_%06d{FRAME_EXT}",
        ]
        self._run_ffmpeg(cmd)

    def probe_video_start_time(self, video_path: Path) -> T.Optional[datetime.datetime]:
        """
        Find video start time of the given video.
        It searches video creation time and duration in video streams first and then the other streams.
        Once found, return stream creation time - stream duration as the video start time.
        """
        probe = self.probe_format_and_streams(video_path)
        streams = probe.get("streams", [])

        # search start time from video streams
        video_streams = [
            stream for stream in streams if stream.get("codec_type") == "video"
        ]
        video_streams.sort(
            key=lambda s: s.get("width", 0) * s.get("height", 0), reverse=True
        )
        for stream in video_streams:
            start_time = extract_stream_start_time(stream)
            if start_time is not None:
                return start_time

        # search start time from the other streams
        for stream in streams:
            if stream.get("codec_type") != "video":
                start_time = extract_stream_start_time(stream)
                if start_time is not None:
                    return start_time

        return None


def extract_stream_start_time(stream: Stream) -> T.Optional[datetime.datetime]:
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
        creation_time = datetime.datetime.strptime(
            creation_time_str, "%Y-%m-%d %H:%M:%S"
        )
    except ValueError:
        creation_time = datetime.datetime.strptime(
            creation_time_str, "%Y-%m-%dT%H:%M:%S.000000Z"
        )

    return creation_time - datetime.timedelta(seconds=duration)


def _extract_idx_from_frame_filename(
    sample_basename: str, video_basename: str
) -> T.Optional[int]:
    video_no_ext, _ = os.path.splitext(video_basename)
    image_no_ext, ext = os.path.splitext(sample_basename)
    if ext == FRAME_EXT and image_no_ext.startswith(f"{video_no_ext}_"):
        n = image_no_ext.replace(f"{video_no_ext}_", "").lstrip("0")
        try:
            return int(n) - 1
        except ValueError:
            return None
    else:
        return None


def list_samples(sample_dir: Path, video_path: Path) -> T.List[T.Tuple[int, Path]]:
    """
    Return a list of tuples: (sample index (0-based), sample path).
    Sample indices are sorted in ascending order.
    """
    samples = []
    for sample_path in sample_dir.iterdir():
        idx = _extract_idx_from_frame_filename(sample_path.name, video_path.name)
        if idx is not None:
            samples.append((idx, sample_path))
    samples.sort()
    return samples
