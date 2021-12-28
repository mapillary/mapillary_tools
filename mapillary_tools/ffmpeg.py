import typing as T
import json
import os
import subprocess
import logging

from . import exceptions

LOG = logging.getLogger(__name__)
MAPILLARY_FFPROBE_PATH = os.getenv("MAPILLARY_FFPROBE_PATH", "ffprobe")
MAPILLARY_FFMPEG_PATH = os.getenv("MAPILLARY_FFMPEG_PATH", "ffmpeg")
FRAME_EXT = ".jpg"


def run_ffprobe_json(cmd: T.List[str]) -> T.Dict:
    full_cmd = [MAPILLARY_FFPROBE_PATH, "-print_format", "json", *cmd]
    LOG.info(f"Extracting video information: {' '.join(full_cmd)}")
    try:
        output = subprocess.check_output(full_cmd)
    except FileNotFoundError:
        raise exceptions.MapillaryFFmpegNotFoundError(
            f'The ffprobe command "{MAPILLARY_FFPROBE_PATH}" not found. Make sure it is installed in your $PATH or it is available in $MAPILLARY_FFPROBE_PATH. See https://github.com/mapillary/mapillary_tools#video-support for instructions'
        )
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"Error JSON decoding ffprobe output: {output.decode('utf-8')}"
        )


def run_ffmpeg(cmd: T.List[str]) -> None:
    full_cmd = [MAPILLARY_FFMPEG_PATH, *cmd]
    LOG.info(f"Extracting frames: {' '.join(full_cmd)}")
    try:
        subprocess.check_call(full_cmd)
    except FileNotFoundError:
        raise exceptions.MapillaryFFmpegNotFoundError(
            f'The ffmpeg command "{MAPILLARY_FFMPEG_PATH}" not found. Make sure it is installed in your $PATH or it is available in $MAPILLARY_FFMPEG_PATH. See https://github.com/mapillary/mapillary_tools#video-support for instructions'
        )


def probe_video_format_and_streams(video_path: str) -> T.Dict:
    if not os.path.isfile(video_path):
        raise exceptions.MapillaryFileNotFoundError(
            f"Video file not found: {video_path}"
        )

    cmd = ["-loglevel", "quiet", "-show_format", "-show_streams", video_path]
    return run_ffprobe_json(cmd)


def probe_video_streams(video_path: str):
    if not os.path.isfile(video_path):
        raise exceptions.MapillaryFileNotFoundError(
            f"Video file not found: {video_path}"
        )

    output = run_ffprobe_json(
        [
            "-loglevel",
            "quiet",
            "-show_streams",
            "-hide_banner",
            video_path,
        ]
    )
    streams = output.get("streams", [])
    return [s for s in streams if s["codec_type"] == "video"]


def extract_stream(source: str, dest: str, stream_id: int) -> None:
    if not os.path.isfile(source):
        raise exceptions.MapillaryFileNotFoundError(f"Video file not found: {source}")

    cmd = [
        "-i",
        source,
        "-y",  # overwrite - potentially dangerous
        "-nostats",
        "-loglevel",
        "0",
        "-hide_banner",
        "-codec",
        "copy",
        "-map",
        f"0:{stream_id}",
        "-f",
        "rawvideo",
        dest,
    ]

    run_ffmpeg(cmd)


def extract_frames(
    video_path: str,
    sample_path: str,
    video_sample_interval: float = 2.0,
) -> None:
    if not os.path.isfile(video_path):
        raise exceptions.MapillaryFileNotFoundError(
            f"Video file not found: {video_path}"
        )

    video_basename_no_ext, ext = os.path.splitext(os.path.basename(video_path))
    frame_path_prefix = os.path.join(sample_path, video_basename_no_ext)
    cmd = [
        "-i",
        video_path,
        "-vf",
        f"fps=1/{video_sample_interval}",
        "-hide_banner",
        # video quality level
        "-qscale:v",
        "1",
        "-nostdin",
        f"{frame_path_prefix}_%06d{FRAME_EXT}",
    ]
    run_ffmpeg(cmd)


def extract_idx_from_frame_filename(
    video_basename: str, image_basename: str
) -> T.Optional[int]:
    video_no_ext, _ = os.path.splitext(video_basename)
    image_no_ext, ext = os.path.splitext(image_basename)
    if ext == FRAME_EXT and image_no_ext.startswith(f"{video_no_ext}_"):
        n = image_no_ext.replace(f"{video_no_ext}_", "").lstrip("0")
        try:
            return int(n) - 1
        except ValueError:
            return None
    else:
        return None
