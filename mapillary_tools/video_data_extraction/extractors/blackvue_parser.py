from __future__ import annotations

import functools

import typing as T

from ... import blackvue_parser, geo
from .base_parser import BaseParser


class BlackVueParser(BaseParser):
    default_source_pattern = "%f"
    must_rebase_times_to_zero = False
    parser_label = "blackvue"

    pointsFound: bool = False

    @functools.cached_property
    def extract_blackvue_info(self) -> blackvue_parser.BlackVueInfo | None:
        source_path = self.geotag_source_path
        if not source_path:
            return None

        with source_path.open("rb") as fp:
            return blackvue_parser.extract_blackvue_info(fp)

    def extract_points(self) -> T.Sequence[geo.Point]:
        blackvue_info = self.extract_blackvue_info

        if blackvue_info is None:
            return []

        return blackvue_info.gps or []

    def extract_make(self) -> str | None:
        blackvue_info = self.extract_blackvue_info

        if blackvue_info is None:
            return None

        return blackvue_info.make

    def extract_model(self) -> str | None:
        blackvue_info = self.extract_blackvue_info

        if blackvue_info is None:
            return None

        return blackvue_info.model
