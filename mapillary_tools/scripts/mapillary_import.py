import argparse
import sys
import os
import datetime
import json
from mapillary_tools.lib.upload import upload
from mapillary_tools.lib import process_video
from mapillary_tools.lib.process_user_properties import process_user_properties
from mapillary_tools.lib.process_import_meta_properties import process_import_meta_properties
from mapillary_tools.lib.process_geotag_properties import process_geotag_properties
from mapillary_tools.lib.process_sequence_properties import process_sequence_properties
from mapillary_tools.lib.process_upload_params import process_upload_params
from mapillary_tools.lib.insert_MAPJson import insert_MAPJson
from mapillary_tools.lib.exif_read import ExifRead
from mapillary_tools.lib.exif_write import ExifEdit


def get_args():
    parser = argparse.ArgumentParser(
        description='Process photos to have them uploaded to Mapillary')

    # path to the import photos
    parser.add_argument('tool', help='Mapillary tool you want to use [upload, process, process_and_upload, process_video, process_and_upload_video, user_process, import_metadata_process,' +
                        'geotag_process, sequence_process, upload_params_process, insert_EXIF_ImageDescription]')

    # force rerun process, will rewrite the json and update the processing logs
    parser.add_argument(
        'path', help='path to your photos, or in case of video, path where the photos from video sampling will be saved')

    # force rerun process, will rewrite the json and update the processing logs
    parser.add_argument(
        '--rerun', help='rerun the processing', action='store_true')

    # user name for the import
    parser.add_argument("--user_name", help="user name")

    # sequence level parameters
    parser.add_argument('--cutoff_distance', default=600., type=float,
                        help='maximum gps distance in meters within a sequence')
    parser.add_argument('--cutoff_time', default=60., type=float,
                        help='maximum time interval in seconds within a sequence')
    parser.add_argument('--interpolate_directions',
                        help='perform interploation of directions', action='store_true')
    parser.add_argument('--offset_angle', default=0., type=float,
                        help='offset camera angle (90 for right facing, 180 for rear facing, -90 for left facing)')
    parser.add_argument('--flag_duplicates',
                        help='flag duplicates', action='store_true')
    parser.add_argument('--duplicate_distance',
                        help='max distance for two images to be considered duplicates in meters', default=0.1)
    parser.add_argument(
        '--duplicate_angle', help='max angle for two images to be considered duplicates in degrees', default=5)

    # geotagging parameters
    parser.add_argument(
        '--geotag_source', help='Provide the source of date/time and gps information needed for geotagging.', action='store',
        choices=['exif', 'gpx', 'csv', 'json'], default="exif")
    parser.add_argument(
        '--geotag_source_path', help='Provide the path to the file source of date/time and gps information needed for geotagging.', action='store',
        default=None)
    parser.add_argument(
        '--local_time', help='Assume image timestamps are in your local time', action='store_true', default=False)
    parser.add_argument('--sub_second_interval',
                        help='Sub second time between shots. Used to set image times with sub-second precision',
                        type=float, default=0.0)
    parser.add_argument('--offset_time', default=0., type=float,
                        help='time offset between the camera and the gps device, in seconds.')

    # organization level parameters
    parser.add_argument(
        '--organization_name', help="Specify organization name", default=None)
    parser.add_argument(
        '--organization_key', help="Specify organization key", default=None)
    parser.add_argument('--private',
                        help="Specify whether the import is private", action='store_true', default=False)

    # import level parameters
    parser.add_argument(
        "--device_make", help="Specify device manufacturer. Note this input has precedence over the input read from the import source file.", default=None)
    parser.add_argument(
        "--device_model", help="Specify device model. Note this input has precedence over the input read from the import source file.", default=None)
    parser.add_argument(
        '--add_file_name', help="Add original file name to EXIF. Note this input has precedence over the input read from the import source file.", action='store_true')
    parser.add_argument(
        '--add_import_date', help="Add import date.", action='store_true')
    parser.add_argument('--orientation', help='Specify the image orientation in degrees. Note this might result in image rotation. Note this input has precedence over the input read from the import source file.',
                        choices=[0, 90, 180, 270], type=int, default=None)
    parser.add_argument(
        "--GPS_accuracy", help="GPS accuracy in meters. Note this input has precedence over the input read from the import source file.", default=None)
    parser.add_argument(
        '--import_meta_source', help='Provide the source of import properties.', action='store',
        choices=['exif', 'json'], default=None)
    parser.add_argument(
        '--import_meta_source_path', help='Provide the path to the file source of import specific information. Note, only JSON format is supported.', action='store',
        default=None)

    # master upload
    parser.add_argument('--master_upload', help='Process images with a master key, note: only used by Mapillary employees',
                        action='store_true', default=False)

    # manually process finalize
    parser.add_argument('--manual_process_finalize',
                        help='Manually finalize the process, resulting in editing image EXIF.', action='store_true', default=False)

    # video
    parser.add_argument(
        '--video_file', help='Provide the path to the video file.', action='store', default=None)
    parser.add_argument(
        '--sample_interval', help='Time interval for sampled video frames in seconds', default=2, type=float)
    parser.add_argument("--skip_sampling",
                        help="Skip video sampling step", action="store_true", default=False)
    parser.add_argument("--use_gps_start_time",
                        help="Use GPS trace starting time as reference for video processing.", action="store_true", default=False)
    parser.add_argument("--video_duration_ratio",
                        help="Real time video duration ratio of the under or oversampled video duration.", type=float, default=1.0)
    parser.add_argument(
        "--video_start_time", help="Video start time in epochs (milliseconds)", type=int, default=None)

    # upload
    parser.add_argument(
        '--manual_done', help='Manually finalize the upload', action='store_true', default=False)

    # verbose, print out warnings and info
    parser.add_argument(
        '--verbose', help='print debug info', action='store_true', default=False)

    return parser.parse_args()


if __name__ == '__main__':
    '''
    '''

    if sys.version_info >= (3, 0):
        raise IOError("Incompatible Python version. This script requires Python 2.x, you are using {0}.".format(
            sys.version_info[:2]))

    args = get_args()

    # INITIAL SANITY CHECKS ---------------------------------------
    # set import path to images
    import_path = os.path.abspath(args.path)
    # check if it exist and exit if it doesnt
    if not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " doesnt not exist, exiting...")
        sys.exit()

    # read the tool and execute it
    tool = args.tool
    if tool not in ("upload", "process", "process_and_upload", "process_video", "process_and_upload_video", "user_process", "import_metadata_process",
                    'geotag_process', 'sequence_process', 'upload_params_process', 'insert_EXIF_ImageDescription'):
        print("Error, tool " + tool + " does not exist, available tools are [upload, process, process_and_upload, process_video, process_and_upload_video, user_process, import_metadata_process," +
              'geotag_process, sequence_process, upload_params_process, insert_EXIF_ImageDescription]')
        sys.exit()

    # set verbose level(only one for now, should have more)
    verbose = args.verbose

    # set rerun flag
    rerun = args.rerun

    # user args
    user_name = args.user_name
    master_upload = args.master_upload

    # organization args
    organization_name = args.organization_name
    organization_key = args.organization_key
    private = args.private

    # import meta data args
    device_make = args.device_make
    device_model = args.device_model
    GPS_accuracy = args.GPS_accuracy
    add_file_name = args.add_file_name
    add_import_date = args.add_import_date
    orientation = args.orientation
    import_meta_source = args.import_meta_source
    import_meta_source_path = args.import_meta_source_path

    # geotag args
    geotag_source = args.geotag_source
    geotag_source_path = args.geotag_source_path
    offset_angle = args.offset_angle
    sub_second_interval = args.sub_second_interval
    local_time = args.local_time
    offset_time = args.offset_time

    # sequence args
    cutoff_distance = args.cutoff_distance
    cutoff_time = args.cutoff_time
    interpolate_directions = args.interpolate_directions
    remove_duplicates = args.flag_duplicates
    duplicate_distance = args.duplicate_distance
    duplicate_angle = args.duplicate_angle

    # upload args
    manual_done = args.manual_done

    # skip args
    manual_process_finalize = args.manual_process_finalize

    # internal args
    timestamp_from_filename = False
    video_duration = None

    # video args
    video_file = args.video_file
    sample_interval = args.sample_interval
    skip_sampling = args.skip_sampling
    use_gps_start_time = args.use_gps_start_time
    video_duration_ratio = args.video_duration_ratio
    video_start_time = args.video_start_time

    # VIDEO PROCESS
    if tool == "process_video" or tool == "process_and_upload_video":
        # sanity checks for video
        # currently only gpx trace if supported as video gps data
        if geotag_source != "gpx":
            if verbose:
                print(
                    "Warning, geotag source not specified to gpx. Currently only gpx trace is supported as the source of video gps data.")
            geotag_source = "gpx"
        if not geotag_source_path or not os.path.isfile(geotag_source_path) or geotag_source_path[-3:] != "gpx":
            print("Error, gpx trace file path not valid or specified. To geotag a video, a valid gpx trace file is required.")
            sys.exit()

        # sample video
        if not skip_sampling:

            process_video.sample_video(video_file,
                                       import_path,  # should all the existing image here be removed prior sampling?
                                       sample_interval)

        # set video args
        video_duration = process_video.get_video_duration(video_file)
        if not use_gps_start_time:
            if video_start_time:
                video_start_time = datetime.datetime.utcfromtimestamp(
                    video_start_time / 1000.)
            else:
                video_start_time = process_video.get_video_start_time(
                    video_file)
        # run the rest on image level
        tool = tool[:-6]
        timestamp_from_filename = True

    # PROCESS USER PROPERTIES --------------------------------------
    if tool == "user_process" or tool == "process" or tool == "process_and_upload":
        # function call
        process_user_properties(import_path,
                                user_name,
                                organization_name,
                                organization_key,
                                private,
                                master_upload,
                                verbose,
                                rerun)
    # PROCESS IMPORT PROPERTIES --------------------------------------
    if tool == "import_metadata_process" or tool == "process" or tool == "process_and_upload":
        # function call
        process_import_meta_properties(import_path,
                                       orientation,
                                       device_make,
                                       device_model,
                                       GPS_accuracy,
                                       add_file_name,
                                       add_import_date,
                                       import_meta_source,
                                       import_meta_source_path,
                                       verbose,
                                       rerun)
    # PROCESS GEO/TIME PROPERTIES --------------------------------------
    if tool == "geotag_process" or tool == "process" or tool == "process_and_upload":
        # function call
        process_geotag_properties(import_path,
                                  geotag_source,
                                  video_duration,
                                  sample_interval,
                                  video_start_time,
                                  use_gps_start_time,
                                  video_duration_ratio,
                                  rerun,
                                  offset_time,
                                  local_time,
                                  sub_second_interval,
                                  geotag_source_path,
                                  offset_angle,
                                  timestamp_from_filename,
                                  verbose)
    # PROCESS SEQUENCE PROPERTIES --------------------------------------
    if tool == "sequence_process" or tool == "process" or tool == "process_and_upload":
        process_sequence_properties(import_path,
                                    cutoff_distance,
                                    cutoff_time,
                                    interpolate_directions,
                                    remove_duplicates,
                                    duplicate_distance,
                                    duplicate_angle,
                                    verbose,
                                    rerun)
    # PROCESS UPLOAD PARAMS PROPERTIES --------------------------------------
    if tool == "upload_params_process" or tool == "process" or tool == "process_and_upload":
        # function call
        process_upload_params(import_path,
                              user_name,
                              master_upload,
                              verbose,
                              rerun)
    # COMBINE META DATA AND INSERT INTO EXIF IMAGE DESCRIPTION ---------------
    if tool == "insert_EXIF_ImageDescription" or tool == "process" or tool == "process_and_upload":
        # function call
        insert_MAPJson(import_path,
                       master_upload,
                       verbose,
                       manual_process_finalize,
                       rerun)
    # UPLOAD
    if tool == "upload" or tool == "process_and_upload":
        upload(import_path,
               manual_done)

    # ---------------------------------------
