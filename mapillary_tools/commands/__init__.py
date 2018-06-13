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
    authenticate
]
mapillary_tools_commands = [
    process,
    upload,
    process_and_upload
]


def add_general_arguments(parser, command):
    parser.add_argument('--advanced', help='Use the tools under an advanced level with additional arguments and tools available.',
                        action='store_true', required=False, default=False)
    if command == "authenticate":
        return
    #import path
    parser.add_argument(
        '--import_path', help='path to your photos, or in case of video, path where the photos from video sampling will be saved', required=True)
    # print out warnings
    parser.add_argument(
        '--verbose', help='print debug info', action='store_true', default=False, required=False)
