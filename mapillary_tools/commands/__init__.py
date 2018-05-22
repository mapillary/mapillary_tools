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
    process,
    process_and_upload,
    video_process,
    video_process_and_upload
]


def add_general_arguments(parser, command):
    #import path
    parser.add_argument(
        '--import_path', help='path to your photos, or in case of video, path where the photos from video sampling will be saved', required=True)
    # skip all subfolders in the import path
    parser.add_argument(
        '--skip_subfolders', help='Skip all subfolders and import only the images in the given directory path.', action='store_true', default=False, required=False)
    # print out warnings
    parser.add_argument(
        '--verbose', help='print debug info', action='store_true', default=False, required=False)
