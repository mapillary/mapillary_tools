import argparse
import sys
import os
import datetime
from mapillary_tools.lib.upload import upload
from mapillary_tools.lib import process_video
from mapillary_tools.lib.process_user_properties import process_user_properties
from mapillary_tools.lib.process_import_meta_properties import process_import_meta_properties
from mapillary_tools.lib.process_geotag_properties import process_geotag_properties
from mapillary_tools.lib.process_sequence_properties import process_sequence_properties
from mapillary_tools.lib.process_upload_params import process_upload_params
from mapillary_tools.lib.insert_MAPJson import insert_MAPJson


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

    # project level parameters
    parser.add_argument(
        '--project', help="add project name in case validation is required", default=None)
    parser.add_argument(
        '--project_key', help="add project to EXIF (project key)", default=None)
    parser.add_argument('--skip_validate_project',
                        help="do not validate project key or projectd name", action='store_true')

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

    # skip certain steps of processing
    parser.add_argument('--skip_user_processing',
                        help='skip the processing of user properties', action='store_true', default=False)
    parser.add_argument('--skip_import_meta_processing',
                        help='skip the processing of import meta data properties', action='store_true', default=False)
    parser.add_argument('--skip_geotagging', help='skip the geotagging',
                        action='store_true', default=False)
    parser.add_argument('--skip_sequence_processing',
                        help='skip the sequence processing', action='store_true', default=False)
    parser.add_argument('--skip_QC', help='skip the quality check',
                        action='store_true', default=False)
    parser.add_argument('--skip_upload_params_processing',
                        help='skip the upload params processing', action='store_true', default=False)
    parser.add_argument('--skip_insert_EXIF',
                        help='skip the insertion of MAPJsons into image EXIF tag Image Description', action='store_true', default=False)

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
        '--auto_done', help='automatically finalize the upload', action='store_true', default=False)

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

    # user args
    user_name = args.user_name
    master_upload = args.master_upload

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
    auto_done = args.auto_done

    # skip args
    skip_user_processing = args.skip_user_processing
    skip_import_meta_processing = args.skip_import_meta_processing
    skip_geotagging = args.skip_geotagging
    skip_sequence_processing = args.skip_sequence_processing
    skip_QC = args.skip_QC
    skip_upload_params_processing = args.skip_upload_params_processing
    skip_insert_EXIF = args.skip_insert_EXIF

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
                                       import_path,
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

    # ADDITIONAL SANITY CHECKS ---------------------------------------
    # get the full image list
    full_image_list = []
    for root, dir, files in os.walk(import_path):
        full_image_list.extend(os.path.join(root, file) for file in files if file.lower(
        ).endswith(('jpg', 'jpeg', 'png', 'tif', 'tiff', 'pgm', 'pnm', 'gif')))
    # check if any images in the list and exit if none
    if not len(full_image_list) and tool not in ["process_video", "process_and_upload_video"]:
        print("Error, no images in the import directory " +
              import_path + " or images dont have the extension .jpg, exiting...")
        sys.exit()
    # ---------------------------------------

    # PROCESS USER PROPERTIES --------------------------------------
    if tool == "user_process" or (((tool == "process") or (tool == "process_and_upload")) and not skip_user_processing):
        # sanity checks
        if not user_name:
            print("Error, must provide a valid user name, exiting...")
            sys.exit()
        # function call
        process_user_properties(full_image_list,
                                import_path,
                                user_name,
                                master_upload,
                                verbose)
    # PROCESS IMPORT PROPERTIES --------------------------------------
    if tool == "import_metadata_process" or (((tool == "process") or (tool == "process_and_upload")) and not skip_import_meta_processing):
        # sanity checks
        if import_meta_source_path == None and import_meta_source != None and import_meta_source != "exif":
            print("Error, if reading import properties from external file, rather than image EXIF or command line arguments, you need to provide full path to the log file.")
            sys.exit()
        elif import_meta_source != None and import_meta_source != "exif" and not os.path.isfile(import_meta_source_path):
            print("Error, " + import_meta_source_path + " file source of import properties does not exist. If reading import properties from external file, rather than image EXIF or command line arguments, you need to provide full path to the log file.")
            sys.exit()
        # function call
        process_import_meta_properties(full_image_list,
                                       import_path,
                                       orientation,
                                       device_make,
                                       device_model,
                                       GPS_accuracy,
                                       add_file_name,
                                       add_import_date,
                                       import_meta_source,
                                       import_meta_source_path,
                                       verbose)
    # PROCESS GEO/TIME PROPERTIES --------------------------------------
    if tool == "geotag_process" or (((tool == "process") or (tool == "process_and_upload")) and not skip_geotagging):
        # sanity checks
        if geotag_source_path == None and geotag_source != "exif":
            # if geotagging from external log file, path to the external log file
            # needs to be provided, if not, exit
            print("Error, if geotagging from external log, rather than image EXIF, you need to provide full path to the log file.")
            sys.exit()
        elif geotag_source != "exif" and not os.path.isfile(geotag_source_path):
            print("Error, " + geotag_source_path +
                  " file source of gps/time properties does not exist. If geotagging from external log, rather than image EXIF, you need to provide full path to the log file.")
            sys.exit()
        # function call
        process_geotag_properties(full_image_list,
                                  import_path,
                                  geotag_source,
                                  video_duration,
                                  sample_interval,
                                  video_start_time,
                                  use_gps_start_time,
                                  video_duration_ratio,
                                  offset_time,
                                  local_time,
                                  sub_second_interval,
                                  geotag_source_path,
                                  offset_angle,
                                  timestamp_from_filename,
                                  verbose)
    # PROCESS SEQUENCE PROPERTIES --------------------------------------
    if tool == "sequence_process" or (((tool == "process") or (tool == "process_and_upload")) and not skip_sequence_processing):
        process_sequence_properties(import_path,
                                    cutoff_distance,
                                    cutoff_time,
                                    interpolate_directions,
                                    remove_duplicates,
                                    duplicate_distance,
                                    duplicate_angle,
                                    verbose)
    # PROCESS UPLOAD PARAMS PROPERTIES --------------------------------------
    if tool == "upload_params_process" or (((tool == "process") or (tool == "process_and_upload")) and not skip_upload_params_processing):
        # sanity checks
        if not user_name:
            print("Error, must provide a valid user name, exiting...")
            sys.exit()
        # function call
        process_upload_params(full_image_list,
                              import_path,
                              user_name,
                              master_upload,
                              verbose)
    # COMBINE META DATA AND INSERT INTO EXIF IMAGE DESCRIPTION ---------------
    if tool == "insert_EXIF_ImageDescription" or tool == "process" or tool == "process_and_upload":
        # function call
        insert_MAPJson(full_image_list,
                       import_path,
                       master_upload,
                       verbose,
                       skip_insert_EXIF)
    # UPLOAD
    if tool == "upload" or tool == "process_and_upload":
        upload(import_path,
               auto_done)

    # ---------------------------------------
