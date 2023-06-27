import argparse
import inspect
import typing as T
from pathlib import Path

from .. import constants
from ..process_geotag_properties import (
    FileType,
    GeotagSource,
    process_finalize,
    process_geotag_properties,
)
from ..process_import_meta_properties import process_import_meta_properties
from ..process_sequence_properties import process_sequence_properties


class Command:
    name = "process"
    help = "process images and videos"

    def add_basic_arguments(self, parser: argparse.ArgumentParser):
        geotag_sources: T.List[GeotagSource] = [
            "blackvue_videos",
            "camm",
            "exif",
            "exiftool",
            "gopro_videos",
            "gpx",
            "nmea",
        ]
        geotag_gpx_based_sources: T.List[GeotagSource] = [
            "gpx",
            "gopro_videos",
            "nmea",
            "blackvue_videos",
            "camm",
        ]
        for source in geotag_gpx_based_sources:
            assert source in geotag_sources

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
            help=f"Process files of the specified types only. Supported file types: {','.join(sorted(t.value for t in FileType))} [default: %(default)s]",
            type=lambda option: set(FileType(t) for t in option.split(",")),
            default=",".join(sorted(t.value for t in FileType)),
            required=False,
        )
        group = parser.add_argument_group(
            f"{constants.ANSI_BOLD}PROCESS EXIF OPTIONS{constants.ANSI_RESET_ALL}"
        )
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
            f"{constants.ANSI_BOLD}PROCESS METADATA OPTIONS{constants.ANSI_RESET_ALL}"
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
        group_metadata.add_argument(
            "--add_file_name",
            help="[DEPRECATED since v0.9.4] Add original file name to EXIF.",
            action="store_true",
            required=False,
        )
        group_metadata.add_argument(
            "--add_import_date",
            help="[DEPRECATED since v0.10.0] Add import date.",
            action="store_true",
            required=False,
        )
        group_metadata.add_argument(
            "--orientation",
            help="Specify the image orientation in degrees. Note this might result in image rotation. Note this input has precedence over the input read from the import source file.",
            choices=[0, 90, 180, 270],
            type=int,
            default=None,
            required=False,
        )
        group_metadata.add_argument(
            "--GPS_accuracy",
            help="GPS accuracy in meters. Note this input has precedence over the input read from the import source file.",
            default=None,
            required=False,
        )
        group_metadata.add_argument(
            "--camera_uuid",
            help="Custom string used to differentiate different captures taken with the same camera make and model.",
            default=None,
            required=False,
        )
        group_metadata.add_argument(
            "--custom_meta_data",
            help='[DEPRECATED since v0.10.0] Add custom meta data to all images. Required format of input is a string, consisting of the meta data name, type and value, separated by a comma for each entry, where entries are separated by semicolon. Supported types are long, double, string, boolean, date. Example for two meta data entries "random_name1,double,12.34;random_name2,long,1234".',
            default=None,
            required=False,
        )

        group_geotagging = parser.add_argument_group(
            f"{constants.ANSI_BOLD}PROCESS GEOTAGGING OPTIONS{constants.ANSI_RESET_ALL}"
        )
        group_geotagging.add_argument(
            "--desc_path",
            help=f'Path to write the extracted metadata (description file) that can be passed to the upload command. The hyphen "-" indicates STDOUT. [default: {{IMPORT_PATH}}/{constants.IMAGE_DESCRIPTION_FILENAME}]',
            default=None,
            required=False,
        )
        group_geotagging.add_argument(
            "--geotag_source",
            help="Provide the source of date/time and GPS information needed for geotagging. [default: %(default)s]",
            action="store",
            choices=geotag_sources,
            default="exif",
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
            f"{constants.ANSI_BOLD}PROCESS SEQUENCE OPTIONS{constants.ANSI_RESET_ALL}"
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
        if (
            "geotag_source" in vars_args
            and vars_args["geotag_source"] == "blackvue_videos"
            and (
                "device_make" not in vars_args
                or ("device_make" in vars_args and not vars_args["device_make"])
            )
        ):
            vars_args["device_make"] = "Blackvue"
        if (
            "device_make" in vars_args
            and vars_args["device_make"]
            and vars_args["device_make"].lower() == "blackvue"
        ):
            vars_args["duplicate_angle"] = 360

        metadatas = process_geotag_properties(
            **(
                {
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(process_geotag_properties).args
                }
            )
        )

        metadatas = process_import_meta_properties(
            metadatas=metadatas,
            **(
                {
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(process_import_meta_properties).args
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
