import typing as T
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
        "-loglevel",
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


class FFProbe:
    video: T.List[dict]
    streams: T.List[dict]

    def __init__(self, video_file: str):
        self.video_file = video_file
        cmd = [
            "ffprobe",
            "-loglevel",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            self.video_file,
        ]
        LOG.info(f"Extracting video information: {' '.join(cmd)}")
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        except FileNotFoundError:
            raise RuntimeError(
                "ffprobe not found. Please make sure it is installed in your PATH. See https://github.com/mapillary/mapillary_tools#video-support for instructions"
            )
        parsed = json.loads(output)
        self.streams = parsed.get("streams", [])
        self.video = [s for s in self.streams if s["codec_type"] == "video"]
        if not self.video:
            raise RuntimeError(f"Not found video streams in {self.video_file}")


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


if __name__ == "__main__":
    import sys

    probe = FFProbe(sys.argv[1])
    print(json.dumps(probe.video))
