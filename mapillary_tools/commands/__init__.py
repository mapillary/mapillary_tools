from . import extract_user_data
from . import extract_geotag_data
from . import extract_import_meta_data
from . import extract_sequence_data
from . import extract_upload_params
from . import exif_insert
from . import upload
from . import sample_video
from . import process
from . import process_and_upload
from . import video_process
from . import video_process_and_upload
from . import process_csv
from . import authenticate
from . import interpolate
from . import post_process
from . import download
from . import send_videos_for_processing

mapillary_tools_advanced_commands = [
    sample_video,
    video_process,
    video_process_and_upload,
    extract_user_data,
    extract_geotag_data,
    extract_import_meta_data,
    extract_sequence_data,
    extract_upload_params,
    exif_insert,
    process_csv,
    authenticate,
    interpolate,
    post_process,
    download,
    send_videos_for_processing
]

mapillary_tools_commands = [
    process,
    upload,
    process_and_upload
]

VERSION = "0.5.3"


def add_general_arguments(parser, command):
    parser.add_argument('--advanced',
        help='Use the tools under an advanced level with additional arguments and tools available.',
        action='store_true', required=False, default=False)
    parser.add_argument('--version',
        help='Print mapillary tools version.',
        action='store_true', required=False, default=False)

    if command == "authenticate":
        return
    # print out warnings
    parser.add_argument('--verbose',
        help='Print debug information.',
        action='store_true', default=False, required=False)
    #import path
    required = True
    if command in ["interpolate", "video_process", "video_process_and_upload", "sample_video", "send_videos_for_processing"]:
        required = False

    parser.add_argument('--import_path',
        help='Path to your photos, or in case of video, path where the photos from video sampling will be saved.',
        required=required)
