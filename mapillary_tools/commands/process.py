from __future__ import annotations

import argparse
import inspect
from pathlib import Path

from .. import constants, types
from ..process_geotag_properties import (
    DEFAULT_GEOTAG_SOURCE_OPTIONS,
    process_finalize,
    process_geotag_properties,
    SourceType,
)
from ..process_sequence_properties import process_sequence_properties


def bold_text(text: str) -> str:
    ANSI_BOLD = "\033[1m"
    ANSI_RESET_ALL = "\033[0m"
    return f"{ANSI_BOLD}{text}{ANSI_RESET_ALL}"


class Command:
    name = "process"
    help = "process images and videos"

    def add_basic_arguments(self, parser: argparse.ArgumentParser):
        geotag_gpx_based_sources: list[str] = [
            SourceType.GPX.value,
            SourceType.NMEA.value,
            SourceType.GOPRO.value,
            SourceType.BLACKVUE.value,
            SourceType.CAMM.value,
        ]

        parser.add_argument(
            "--skip_process_errors",
            help="Skip process errors.",
            action="store_true",
            default=False,
            required=False,
        )
        parser.add_argument(
            "--filetypes",
            "--file_types",
            help=f"Process files of the specified types only. Supported file types: {','.join(sorted(t.value for t in types.FileType))} [default: %(default)s]",
            type=lambda option: set(types.FileType(t) for t in option.split(",")),
            default=None,
            required=False,
        )
        group = parser.add_argument_group(bold_text("PROCESS EXIF OPTIONS"))
        group.add_argument(
            "--overwrite_all_EXIF_tags",
            help="Overwrite all of the relevant EXIF tags with the values obtained in process. It is equivalent to supplying all the --overwrite_EXIF_*_tag flags.",
            action="store_true",
            default=False,
            required=False,
        )
        group.add_argument(
            "--overwrite_EXIF_time_tag",
            help="Overwrite the capture time EXIF tag with the value obtained in process.",
            action="store_true",
            default=False,
            required=False,
        )
        group.add_argument(
            "--overwrite_EXIF_gps_tag",
            help="Overwrite the GPS EXIF tag with the value obtained in process.",
            action="store_true",
            default=False,
            required=False,
        )
        group.add_argument(
            "--overwrite_EXIF_direction_tag",
            help="Overwrite the camera direction EXIF tag with the value obtained in process.",
            action="store_true",
            default=False,
            required=False,
        )
        group.add_argument(
            "--overwrite_EXIF_orientation_tag",
            help="Overwrite the orientation EXIF tag with the value obtained in process.",
            action="store_true",
            default=False,
            required=False,
        )

        group_metadata = parser.add_argument_group(
            bold_text("PROCESS METADATA OPTIONS")
        )
        group_metadata.add_argument(
            "--device_make",
            help="Specify device manufacturer. Note this input has precedence over the input read from the import source file.",
            default=None,
            required=False,
        )
        group_metadata.add_argument(
            "--device_model",
            help="Specify device model. Note this input has precedence over the input read from the import source file.",
            default=None,
            required=False,
        )

        group_geotagging = parser.add_argument_group(
            bold_text("PROCESS GEOTAGGING OPTIONS")
        )
        group_geotagging.add_argument(
            "--desc_path",
            help=f'Path to write the extracted metadata (description file) that can be passed to the upload command. The hyphen "-" indicates STDOUT. [default: {{IMPORT_PATH}}/{constants.IMAGE_DESCRIPTION_FILENAME}]',
            default=None,
            required=False,
        )
        group_geotagging.add_argument(
            "--geotag_source",
            help=f"Provide the source of date/time and GPS information needed for geotagging. Supported source types: {', '.join(g.value for g in SourceType)} [default: {','.join(DEFAULT_GEOTAG_SOURCE_OPTIONS)}]",
            action="append",
            default=[],
            required=False,
        )
        group_geotagging.add_argument(
            "--geotag_source_path",
            help="Provide the path to the file source of date/time and GPS information needed for geotagging.",
            action="store",
            default=None,
            required=False,
            type=Path,
        )
        group_geotagging.add_argument(
            "--video_geotag_source",
            help="Name of the video data extractor and optional arguments. Can be specified multiple times. See the documentation for details. [Experimental, subject to change]",
            action="append",
            default=[],
            required=False,
        )
        group_geotagging.add_argument(
            "--interpolation_use_gpx_start_time",
            help=f"If supplied, the first image will use the first GPX point time for interpolation, which means the image location will be interpolated to the first GPX point too. Only works for geotagging from {', '.join(geotag_gpx_based_sources)}.",
            action="store_true",
            required=False,
        )
        group_geotagging.add_argument(
            "--interpolation_offset_time",
            default=0.0,
            type=float,
            help=f"Time offset, in seconds, that will be added for GPX interpolation, which affects image locations. Note that it is applied after --interpolation_use_gpx_start_time. Only works for geotagging from {', '.join(geotag_gpx_based_sources)}. [default %(default)s]",
            required=False,
        )
        group_geotagging.add_argument(
            "--offset_angle",
            default=0.0,
            type=float,
            help="Camera angle offset, in degrees, that will be added to your image camera angles after geotagging/interpolation. [default: %(default)s]",
            required=False,
        )
        group_geotagging.add_argument(
            "--offset_time",
            default=0.0,
            type=float,
            help="Time offset, in seconds, that will be added to your image timestamps after geotagging/interpolation. [default: %(default)s]",
            required=False,
        )
        group_geotagging.add_argument(
            "--num_processes",
            help="The number of processes for processing the data concurrently. A non-positive number (N<=0) will disable multiprocessing (useful for debugging). [default: the number of CPUs]",
            type=int,
            required=False,
        )

        group_sequence = parser.add_argument_group(
            bold_text("PROCESS SEQUENCE OPTIONS")
        )
        group_sequence.add_argument(
            "--cutoff_distance",
            default=constants.CUTOFF_DISTANCE,
            type=float,
            help="Cut a sequence from where the distance between adjacent images exceeds CUTOFF_DISTANCE. [default: %(default)s]",
            required=False,
        )
        group_sequence.add_argument(
            "--cutoff_time",
            default=constants.CUTOFF_TIME,
            type=float,
            help="Cut a sequence from where the capture time difference between adjacent images exceeds CUTOFF_TIME. [default: %(default)s]",
            required=False,
        )
        group_sequence.add_argument(
            "--interpolate_directions",
            help="Change each image's camera angle to point to its next image.",
            action="store_true",
            required=False,
        )
        group_sequence.add_argument(
            "--duplicate_distance",
            help='The maximum distance that can be considered "too close" between two images. If both images also point in the same direction (see --duplicate_angle), the later image will be marked as duplicate and will not be upload. [default: %(default)s]',
            type=float,
            default=constants.DUPLICATE_DISTANCE,
            required=False,
        )
        group_sequence.add_argument(
            "--duplicate_angle",
            help="The maximum camera angle difference between two images to be considered as heading in the same direction. If both images are also close to each other (see --duplicate_distance), the later image will be marked as duplicate and will not be upload. [default: %(default)s]",
            type=float,
            default=constants.DUPLICATE_ANGLE,
            required=False,
        )

    def run(self, vars_args: dict):
        metadatas = process_geotag_properties(
            **(
                {
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(process_geotag_properties).args
                }
            ),
        )

        metadatas = process_sequence_properties(
            metadatas=metadatas,
            **(
                {
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(process_sequence_properties).args
                }
            ),
        )

        metadatas = process_finalize(
            metadatas=metadatas,
            **(
                {
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(process_finalize).args
                }
            ),
        )

        # running video_process will pass the metadatas to the upload command
        vars_args["_metadatas_from_process"] = metadatas
