import glob
import re
import typing as T
from os import path
from pathlib import Path

from mapillary_tools import exceptions


def _check_single_geotag_source(video_paths: T.Sequence[Path], geotag_source_path: Path) -> T.Dict[Path, Path]:
    if 0 < len(video_paths):
        raise exceptions.MapillaryBadParameterError(
            "Cannot use a single geotag file for multiple videos"
        )
    if not geotag_source_path.is_file():
        raise exceptions.MapillaryFileNotFoundError(
            f"Geotag source file not found: {geotag_source_path}"
        )
    
    return {video_paths[0]: geotag_source_path}


def _find_geotag_video_pairs(
    video_paths: T.Sequence[Path],
    geotag_file_extensions: T.List[str],
) -> T.Dict[Path, Path]:
    extension_regex = re.compile(
        f".({'|'.join(geotag_file_extensions)})$", re.IGNORECASE
    )
    video_geotag_pairs: T.Dict[Path, Path] = {}
    for video_path in video_paths:
        video_basename = path.splitext(video_path)[0]
        candidates = glob.glob(f"{video_basename}.*")
        for candidate in candidates:
            if extension_regex.search(candidate):
                if path.isfile(candidate):
                    video_geotag_pairs[video_path] = Path(candidate)
    
    _check_video_geotag_pairs(video_paths, video_geotag_pairs)

    return video_geotag_pairs


def _check_video_geotag_pairs(video_paths: T.Sequence[Path], video_geotag_pairs: T.Dict[Path, Path]):
    if len(video_geotag_pairs) != len(video_paths):
        videos_list = set(video_paths).difference(video_geotag_pairs.keys())
        raise exceptions.MapillaryFileNotFoundError(
            f"Missing geotag file for video(s): {videos_list}"
        )
        # TODO: With --skip errors, we should probably process only the files with geotags


def match_videos_and_geotag_files(
    video_paths: T.Sequence[Path],
    geotag_source_path: Path,
    geotag_file_extensions: T.List[str],
) -> T.Dict[Path, Path]:
    if geotag_source_path:
        return _check_single_geotag_source(video_paths, geotag_source_path)
    else:
        pairings = _find_geotag_video_pairs(video_paths, geotag_file_extensions)
        _check_video_geotag_pairs(video_paths, pairings)
        return pairings
