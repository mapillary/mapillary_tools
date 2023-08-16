import copy
import functools
import subprocess
import tempfile
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

from mapillary_tools import exceptions, geo
from mapillary_tools.data_extractors.base_parser import BaseParser
from mapillary_tools.data_extractors.exiftool_rdf_parser import ExiftoolRdfParser
from mapillary_tools.exiftool_read_video import ExifToolReadVideo
from mapillary_tools.geotag import geotag_images_from_gpx_file
from mapillary_tools.video_data_extraction.options import Options


class ExiftoolRuntimeParser(BaseParser):
    """
    Wrapper around ExiftoolRdfParser that executes exiftool
    """

    exiftoolRdfPath: T.Optional[Path]

    def __init__(self, file_path: Path, options: Options) -> None:
        super().__init__(file_path, options)
        self.exiftoolRdfPath = None

    @functools.cache
    def _get_exiftool_rdf_parser(self) -> ExiftoolRdfParser:
        exiftool_rdf = tempfile.NamedTemporaryFile(delete=False)
        exiftool_rdf_path = Path(exiftool_rdf.name)
        args = f"{self.options['exiftool_path']} -q -w! {exiftool_rdf.name}%0f -r -n -ee -api LargeFileSupport=1 -X {self.videoPath}".split(
            " "
        )
        subprocess.run(args)

        options = copy.deepcopy(self.options)
        options["geotag_source_path"] = exiftool_rdf_path
        self.exiftoolRdfPath = exiftool_rdf_path

        return ExiftoolRdfParser(exiftool_rdf_path, options)

    def extract_points(self) -> T.Sequence[geo.Point]:
        return self._get_exiftool_rdf_parser().extract_points()

    def extract_make(self) -> T.Optional[str]:
        return self._get_exiftool_rdf_parser().extract_make()

    def extract_model(self) -> T.Optional[str]:
        return self._get_exiftool_rdf_parser().extract_model()

    def cleanup(self) -> None:
        if self.exiftoolRdfPath:
            self.exiftoolRdfPath.unlink(missing_ok=True)

    @staticmethod
    def must_rebase_times_to_zero() -> bool:
        return True
