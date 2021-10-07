import logging
import typing as T
import json
import subprocess


LOG = logging.getLogger(__name__)


class FFProbe:
    video: T.List[dict]
    streams: T.List[dict]

    def __init__(self, video_file: str):
        self.video_file = video_file
        cmd = [
            "ffprobe",
            "-loglevel",
            "quiet",
            "-show_streams",
            "-print_format",
            "json",
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


if __name__ == "__main__":
    import sys

    probe = FFProbe(sys.argv[1])
    print(json.dumps(probe.video))
