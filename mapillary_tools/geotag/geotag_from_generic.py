import abc
import typing as T
from os import path
from pathlib import Path

from mapillary_tools import exceptions

from .. import types


class GeotagImagesFromGeneric(abc.ABC):
    def __init__(self) -> None:
        pass

    @abc.abstractmethod
    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        raise NotImplementedError


class GeotagVideosFromGeneric(abc.ABC):
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        num_processes: T.Optional[int] = None,
    ) -> None:
        self.video_paths = video_paths
        self.num_processes = num_processes

    @abc.abstractmethod
    def to_description(self) -> T.List[types.VideoMetadataOrError]:
        raise NotImplementedError

    def match_videos_and_geotag_files(
        self, geotag_source_path: Path, geotag_file_extensions: T.List[str]
    ) -> T.Dict[Path, Path]:
        if geotag_source_path:
            if 0 < len(self.video_paths):
                raise exceptions.MapillaryBadParameterError(
                    "Cannot use a single geotag file for multiple videos"
                )
            if not geotag_source_path.is_file():
                raise exceptions.MapillaryFileNotFoundError(
                    f"Geotag source file not found: {geotag_source_path}"
                )
            return {self.video_paths[0]: geotag_source_path}

        video_geotag_pairs: T.Dict[Path, Path] = {}
        for video_path in self.video_paths:
            video_basename = path.splitext(video_path)[0]
            for ext in geotag_file_extensions:
                geotag_path = Path(f"{video_basename}.{ext}")
                if geotag_path.is_file():
                    video_geotag_pairs[video_path] = geotag_path

        if len(video_geotag_pairs) != len(self.video_paths):
            videos_list = set(self.video_paths).difference(video_geotag_pairs.keys())
            raise exceptions.MapillaryFileNotFoundError(
                f"Missing geotag file for video(s): {videos_list}"
            )
            # TODO: With --skip errors, we should probably process only the files with geotags

        return video_geotag_pairs
