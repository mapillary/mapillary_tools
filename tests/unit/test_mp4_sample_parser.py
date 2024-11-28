from pathlib import Path

from mapillary_tools.mp4 import mp4_sample_parser


def test_movie_box_parser():
    moov_parser = mp4_sample_parser.MovieBoxParser.parse_file(
        Path("tests/data/videos/sample-5s.mp4")
    )
    assert 2 == len(list(moov_parser.extract_tracks()))
    video_track = moov_parser.extract_track_at(0)
    assert video_track.is_video_track()
    aac_track = moov_parser.extract_track_at(1)
    assert not aac_track.is_video_track()
    samples = list(video_track.extract_samples())
    raw_samples = list(video_track.extract_raw_samples())
    assert 171 == len(samples)
    assert len(samples) == len(raw_samples)
    assert {
        "version": 0,
        "flags": 3,
        "creation_time": 0,
        "modification_time": 0,
        "track_ID": 1,
        "duration": 5700,
        "layer": 0,
        "alternate_group": 0,
        "volume": 0,
        # "matrix": [65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824],
        "width": 125829120,
        "height": 70778880,
    } == {
        k: v
        for k, v in video_track.extract_tkhd_boxdata().items()
        if k
        in [
            "version",
            "flags",
            "creation_time",
            "modification_time",
            "track_ID",
            "duration",
            "layer",
            "alternate_group",
            "volume",
            "width",
            "height",
        ]
    }
    assert isinstance(video_track.extract_tkhd_boxdata(), dict)
    for sample, raw_sample in zip(samples, raw_samples):
        assert sample.raw_sample.offset == raw_sample.offset
        assert sample.raw_sample.is_sync == raw_sample.is_sync
        assert sample.raw_sample.size == raw_sample.size
