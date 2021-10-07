import json
import os
import subprocess
import logging

LOG = logging.getLogger(__name__)


def get_ffprobe(path: str) -> dict:
    if not os.path.isfile(path):
        raise RuntimeError(f"No such file: {path}")

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    LOG.info(f"Extracting video information: {' '.join(cmd)}")
    try:
        output = subprocess.check_output(cmd)
    except FileNotFoundError:
        raise RuntimeError(
            "ffprobe not found. Please make sure it is installed in your PATH. See https://github.com/mapillary/mapillary_tools#video-support for instructions"
        )

    try:
        j_obj = json.loads(output)
    except json.JSONDecodeError:
        raise RuntimeError(f"Error JSON decoding {output.decode('utf-8')}")

    return j_obj


def extract_stream(source: str, dest: str, stream_id: int) -> None:
    if not os.path.isfile(source):
        raise RuntimeError(f"No such file: {source}")

    cmd = [
        "ffmpeg",
        "-i",
        source,
        "-y",  # overwrite - potentially dangerous
        "-nostats",
        "-loglevel",
        "0",
        "-codec",
        "copy",
        "-map",
        "0:" + str(stream_id),
        "-f",
        "rawvideo",
        dest,
    ]

    LOG.info(f"Extracting frames: {' '.join(cmd)}")
    try:
        subprocess.check_output(cmd)
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg not found. Please make sure it is installed in your PATH. See https://github.com/mapillary/mapillary_tools#video-support for instructions"
        )
