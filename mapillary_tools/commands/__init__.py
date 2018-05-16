from . import extract_user_data
from . import extract_geotag_data
from . import extract_import_meta_data
from . import extract_sequence_data
from . import extract_upload_params
from . import exif_insert
from . import upload
from . import sample_video

mapillary_tools_process_unit_commands = [
    extract_user_data,
    extract_geotag_data,
    extract_import_meta_data,
    extract_sequence_data,
    extract_upload_params,
    exif_insert
]
mapillary_tools_upload_unit_commands = [
    upload
]
mapillary_tools_video_unit_commands = [
    sample_video
]

mapillary_tools_batch_commands = [
    "process",
    "process_and_upload",
    "video_process",
    "video_process_and_upload"
]


def add_general_arguments(parser, command):
    #import path
    parser.add_argument(
        'path', help='path to your photos, or in case of video, path where the photos from video sampling will be saved')
    # skip all subfolders in the import path
    parser.add_argument(
        '--skip_subfolders', help='Skip all subfolders and import only the images in the given directory path.', action='store_true', default=False, required=False)
    # print out warnings
    parser.add_argument(
        '--verbose', help='print debug info', action='store_true', default=False, required=False)
    # rerun the process
    parser.add_argument(
        '--rerun', help='rerun the processing', action='store_true', required=False)
    if command == "extract_user_data" or command == "extract_upload_params" or command in mapillary_tools_batch_commands:
        # user name for the import
        parser.add_argument("--user_name", help="user name", required=True)
        # master upload
        parser.add_argument('--master_upload', help='Process images with a master key, note: only used by Mapillary employees',
                            action='store_true', default=False, required=False)
    if command == "extract_geotag_data" or command == "extract_sequence_data" or command in mapillary_tools_batch_commands:
        parser.add_argument('--offset_angle', default=0., type=float,
                            help='offset camera angle (90 for right facing, 180 for rear facing, -90 for left facing)', required=False)
