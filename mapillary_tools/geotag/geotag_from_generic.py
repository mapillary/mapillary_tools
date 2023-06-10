import abc
import typing as T

from .. import types


class GeotagImagesFromGeneric(abc.ABC):
    def __init__(self) -> None:
        pass

    @abc.abstractmethod
    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        raise NotImplementedError


class GeotagVideosFromGeneric(abc.ABC):
    def __init__(self) -> None:
        pass

    @abc.abstractmethod
    def to_description(self) -> T.List[types.VideoMetadataOrError]:
        raise NotImplementedError
