# pyre-ignore-all-errors[5, 24]

import datetime
import json
import logging
import os
import re
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
NA_STREAM_ID = "NA"


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
        stream_id: T.Optional[int] = None,
    ) -> None:
        sample_prefix = sample_dir.joinpath(video_path.stem)
        if stream_id is not None:
            stream_selector = ["-map", f"0:{stream_id}"]
            ouput_template = f"{sample_prefix}_{stream_id}_%06d{FRAME_EXT}"
        else:
            stream_selector = []
            ouput_template = f"{sample_prefix}_{NA_STREAM_ID}_%06d{FRAME_EXT}"

        cmd = [
            # global options should be specified first
            *["-hide_banner", "-nostdin"],
            # input 0
            *["-i", str(video_path)],
            # select stream
            *stream_selector,
            # filter videos
            *["-vf", f"fps=1/{sample_interval}"],
            # video quality level (or the alias -q:v)
            *["-qscale:v", "2"],
            # -q:v=1 is the best quality but larger image sizes
            # see https://stackoverflow.com/a/10234065
            # *["-qscale:v", "1", "-qmin", "1"],
            # output
            ouput_template,
        ]

        self._run_ffmpeg(cmd)

    def probe_video_streams(self, video_path: Path) -> T.List[Stream]:
        probe = self.probe_format_and_streams(video_path)
        streams = probe.get("streams", [])
        return [stream for stream in streams if stream.get("codec_type") == "video"]

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


def _extract_stream_frame_idx(
    sample_basename: str,
    sample_basename_pattern: T.Pattern[str],
) -> T.Optional[T.Tuple[T.Optional[int], int]]:
    image_no_ext, ext = os.path.splitext(sample_basename)
    if ext.lower() != FRAME_EXT.lower():
        return None

    match = sample_basename_pattern.match(image_no_ext)
    if not match:
        return None

    g1 = match.group("stream_id")
    try:
        if g1 == NA_STREAM_ID:
            stream_id = None
        else:
            stream_id = int(g1)
    except ValueError:
        return None

    g2 = match.group("frame_idx")
    try:
        frame_idx = int(g2.lstrip("0"))
    except ValueError:
        return None

    return stream_id, frame_idx - 1


def iterate_samples(
    sample_dir: Path, video_path: Path
) -> T.Generator[T.Tuple[T.Optional[int], int, Path], None, None]:
    """
    Search all samples in the sample_dir,
    and return a generator of the tuple: (stream ID, frame index (0-based), sample path).
    Sample indices are sorted in ascending order.
    """
    sample_basename_pattern = re.compile(
        rf"^{re.escape(video_path.stem)}_(?P<stream_id>\d+|{re.escape(NA_STREAM_ID)})_(?P<frame_idx>\d+)$"
    )
    for sample_path in sample_dir.iterdir():
        stream_frame_idx = _extract_stream_frame_idx(
            sample_path.name,
            sample_basename_pattern,
        )
        if stream_frame_idx is not None:
            stream_id, frame_idx = stream_frame_idx
            yield (stream_id, frame_idx, sample_path)


def sort_selected_samples(
    sample_dir: Path, video_path: Path, selected_stream_ids: T.List[T.Optional[int]]
) -> T.List[T.Tuple[int, T.List[T.Optional[Path]]]]:
    """
    Group frames by frame index, so that
    the Nth group contains all the frames from the selected streams at frame index N.
    """
    stream_samples: T.Dict[int, T.List[T.Tuple[T.Optional[int], Path]]] = {}
    for stream_id, frame_idx, sample_path in iterate_samples(sample_dir, video_path):
        stream_samples.setdefault(frame_idx, []).append((stream_id, sample_path))

    selected: T.List[T.Tuple[int, T.List[T.Optional[Path]]]] = []
    for frame_idx in sorted(stream_samples.keys()):
        indexed = {
            stream_id: sample_path
            for stream_id, sample_path in stream_samples[frame_idx]
        }
        selected_sample_paths = [
            indexed.get(stream_id) for stream_id in selected_stream_ids
        ]
        selected.append((frame_idx, selected_sample_paths))
    return selected
