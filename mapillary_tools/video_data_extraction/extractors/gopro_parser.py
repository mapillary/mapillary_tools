from __future__ import annotations

import typing as T

from ... import geo
from ...gpmf import gpmf_parser
from ...mp4 import simple_mp4_parser as sparser
from .base_parser import BaseParser


class GoProParser(BaseParser):
    default_source_pattern = "%f"
    must_rebase_times_to_zero = False
    parser_label = "gopro"

    _extracted: bool = False
    _cached_gopro_info: gpmf_parser.GoProInfo | None = None

    def _extract_gopro_info(self) -> gpmf_parser.GoProInfo | None:
        if self._extracted:
            return self._cached_gopro_info

        self._extracted = True

        source_path = self.geotag_source_path

        if source_path is None:
            # source_path not found
            return None

        with source_path.open("rb") as fp:
            try:
                self._cached_gopro_info = gpmf_parser.extract_gopro_info(fp)
            except sparser.ParsingError:
                self._cached_gopro_info = None

        return self._cached_gopro_info

    def extract_points(self) -> T.Sequence[geo.Point]:
        gopro_info = self._extract_gopro_info()
        if gopro_info is None:
            return []

        return T.cast(T.Sequence[geo.Point], gopro_info.gps)

    def extract_make(self) -> str | None:
        gopro_info = self._extract_gopro_info()
        if gopro_info is None:
            return None

        return gopro_info.make

    def extract_model(self) -> str | None:
        gopro_info = self._extract_gopro_info()
        if gopro_info is None:
            return None

        return gopro_info.model
