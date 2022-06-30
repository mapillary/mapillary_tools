import os
import typing as T
import json
import shutil

from mapillary_tools import sample_video, ffmpeg

_PWD = os.path.dirname(os.path.abspath(__file__))


def mock_extract_frames(
    video_path: str,
    sample_path: str,
    video_sample_interval: float,
):
    video_streams = mock_probe_video_streams(video_path)
    duration = float(video_streams[0]["duration"])
    video_basename_no_ext, _ = os.path.splitext(os.path.basename(video_path))
    frame_path_prefix = os.path.join(sample_path, video_basename_no_ext)
    src = os.path.join(_PWD, "data/test_exif.jpg")
    for idx in range(0, int(duration / video_sample_interval)):
        sample = f"{frame_path_prefix}_{idx:06d}.jpg"
        print(sample)
        shutil.copyfile(src, sample)


def mock_probe_video_streams(video_path: str) -> T.List[T.Dict]:
    with open(video_path) as fp:
        ffprobe_output = json.load(fp)
    streams = ffprobe_output.get("streams", [])
    return [s for s in streams if s["codec_type"] == "video"]


def test_sample_video(monkeypatch):
    monkeypatch.setattr(ffmpeg, "extract_frames", mock_extract_frames)
    monkeypatch.setattr(ffmpeg, "probe_video_streams", mock_probe_video_streams)
    root = os.path.join(_PWD, "data/mock_sample_video")
    video_dir = os.path.join(root, "videos")
    sample_dir = os.path.join(root, "samples")
    sample_video.sample_video(video_dir, sample_dir)
    print(sample_dir, os.listdir(sample_dir))
