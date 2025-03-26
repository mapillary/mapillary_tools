from __future__ import annotations

import typing as T

from ... import geo
from ...camm import camm_parser
from ...mp4 import simple_mp4_parser as sparser
from .base_parser import BaseParser


class CammParser(BaseParser):
    default_source_pattern = "%f"
    must_rebase_times_to_zero = False
    parser_label = "camm"

    _extracted: bool = False
    _cached_camm_info: camm_parser.CAMMInfo | None = None

    # TODO: use @functools.cached_property
    def _extract_camm_info(self) -> camm_parser.CAMMInfo | None:
        if self._extracted:
            return self._cached_camm_info

        self._extracted = True

        source_path = self.geotag_source_path

        if source_path is None:
            # source_path not found
            return None

        with source_path.open("rb") as fp:
            try:
                self._cached_camm_info = camm_parser.extract_camm_info(fp)
            except sparser.ParsingError:
                self._cached_camm_info = None

        return self._cached_camm_info

    def extract_points(self) -> T.Sequence[geo.Point]:
        camm_info = self._extract_camm_info()

        if camm_info is None:
            return []

        return T.cast(T.List[geo.Point], camm_info.gps or camm_info.mini_gps)

    def extract_make(self) -> str | None:
        camm_info = self._extract_camm_info()

        if camm_info is None:
            return None

        return camm_info.make

    def extract_model(self) -> str | None:
        camm_info = self._extract_camm_info()

        if camm_info is None:
            return None

        return camm_info.model
