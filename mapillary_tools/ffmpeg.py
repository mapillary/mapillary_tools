import json
import logging
import os
import shutil
import subprocess
import time
import typing as T
from pathlib import Path
from contextlib import contextmanager

LOG = logging.getLogger(__name__)
MAPILLARY_FFPROBE_PATH = os.getenv("MAPILLARY_FFPROBE_PATH", "ffprobe")
MAPILLARY_FFMPEG_PATH = os.getenv("MAPILLARY_FFMPEG_PATH", "ffmpeg")
FRAME_EXT = ".jpg"


class FFmpegNotFoundError(Exception):
    pass


def _run_ffprobe_json(cmd: T.List[str]) -> T.Dict:
    full_cmd = [MAPILLARY_FFPROBE_PATH, "-print_format", "json", *cmd]
    LOG.info(f"Extracting video information: {' '.join(full_cmd)}")
    try:
        output = subprocess.check_output(full_cmd)
    except FileNotFoundError:
        raise FFmpegNotFoundError(
            f'The ffprobe command "{MAPILLARY_FFPROBE_PATH}" is not found in your $PATH or $MAPILLARY_FFPROBE_PATH'
        )
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"Error JSON decoding ffprobe output: {output.decode('utf-8')}"
        )


def _run_ffmpeg(cmd: T.List[str]) -> None:
    full_cmd = [MAPILLARY_FFMPEG_PATH, *cmd]
    LOG.info(f"Extracting frames: {' '.join(full_cmd)}")
    try:
        subprocess.check_call(full_cmd)
    except FileNotFoundError:
        raise FFmpegNotFoundError(
            f'The ffmpeg command "{MAPILLARY_FFMPEG_PATH}" is not found in your $PATH or $MAPILLARY_FFMPEG_PATH'
        )


def probe_video_format_and_streams(video_path: Path) -> T.Dict:
    cmd = ["-loglevel", "quiet", "-show_format", "-show_streams", str(video_path)]
    return _run_ffprobe_json(cmd)


def probe_video_streams(video_path: Path) -> T.List[T.Dict]:
    output = _run_ffprobe_json(
        [
            "-loglevel",
            "quiet",
            "-show_streams",
            "-hide_banner",
            str(video_path),
        ]
    )
    streams = output.get("streams", [])
    return [s for s in streams if s["codec_type"] == "video"]


def extract_stream(source: Path, dest: Path, stream_id: int) -> None:
    cmd = [
        "-i",
        str(source),
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
        str(dest),
    ]

    _run_ffmpeg(cmd)


def extract_frames(
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
    _run_ffmpeg(cmd)


def extract_idx_from_frame_filename(
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


@contextmanager
def wip_dir_context(wip_dir: Path, done_dir: Path):
    assert wip_dir != done_dir, "should not be the same dir"
    shutil.rmtree(wip_dir, ignore_errors=True)
    os.makedirs(wip_dir)
    try:
        yield wip_dir
        shutil.rmtree(done_dir, ignore_errors=True)
        wip_dir.rename(done_dir)
    finally:
        shutil.rmtree(wip_dir, ignore_errors=True)


def wip_sample_dir(sample_dir: Path) -> Path:
    pid = os.getpid()
    timestamp = int(time.time())
    # prefix with .mly_ffmpeg_ to avoid samples being scanned by "mapillary_tools process"
    return sample_dir.parent.joinpath(
        f".mly_ffmpeg_{sample_dir.name}.{pid}.{timestamp}"
    )


def list_samples(sample_dir: Path, video_path: Path) -> T.List[T.Tuple[int, Path]]:
    samples = []
    for sample_path in sample_dir.iterdir():
        idx = extract_idx_from_frame_filename(sample_path.name, video_path.name)
        if idx is not None:
            samples.append((idx, sample_path))
    samples.sort()
    return samples


def sample_video_wip(
    video_path: Path,
    sample_dir: Path,
    sample_interval: float,
) -> T.Generator[T.Tuple[int, Path], None, None]:
    with wip_dir_context(wip_sample_dir(sample_dir), sample_dir) as wip_dir:
        extract_frames(
            video_path,
            wip_dir,
            sample_interval,
        )
        for idx, sample in list_samples(wip_dir, video_path):
            yield idx, sample
