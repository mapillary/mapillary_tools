import typing as T

from .. import types


class GeotagImagesFromGeneric:
    def __init__(self) -> None:
        pass

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        return []


class GeotagVideosFromGeneric:
    def __init__(self) -> None:
        pass

    def to_description(self) -> T.List[types.VideoMetadataOrError]:
        return []
