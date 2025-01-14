import dataclasses
import typing as T
from enum import Enum, unique

from .geo import Point


@unique
class GPSFix(Enum):
    NO_FIX = 0
    FIX_2D = 2
    FIX_3D = 3


@dataclasses.dataclass
class GPSPoint(Point):
    epoch_time: T.Optional[float]
    fix: T.Optional[GPSFix]
    precision: T.Optional[float]
    ground_speed: T.Optional[float]
