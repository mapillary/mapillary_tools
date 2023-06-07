import typing as T

from .. import types


class GeotagFromGeneric:
    def __init__(self) -> None:
        pass

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        return []


class GeotagFromVideoGeneric:
    def __init__(self) -> None:
        pass

    def to_description(self) -> T.List[types.VideoMetadataOrError]:
        return []
