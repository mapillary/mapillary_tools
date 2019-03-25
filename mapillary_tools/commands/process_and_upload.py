import inspect
from mapillary_tools.process_user_properties import process_user_properties
from mapillary_tools.process_import_meta_properties import process_import_meta_properties
from mapillary_tools.process_geotag_properties import process_geotag_properties
from mapillary_tools.process_sequence_properties import process_sequence_properties
from mapillary_tools.process_upload_params import process_upload_params
from mapillary_tools.insert_MAPJson import insert_MAPJson
from mapillary_tools.upload import upload
from mapillary_tools.post_process import post_process


class Command:
    name = 'process_and_upload'
    help = "Batch tool : Process images and upload to Mapillary."

    def add_basic_arguments(self, parser):
        # user properties
        # user name for the import
        parser.add_argument("--user_name", help="user name", required=True)
        # organization level parameters
        parser.add_argument(
            '--organization_username', help="Specify organization user name", default=None, required=False)
        parser.add_argument(
            '--organization_key', help="Specify organization key", default=None, required=False)
        parser.add_argument('--private',
                            help="Specify whether the import is private", action='store_true', default=False, required=False)

    def add_advanced_arguments(self, parser):
        # master upload
        parser.add_argument('--master_upload', help='Process images with a master key, note: only used by Mapillary employees',
                            action='store_true', default=False, required=False)
        #import meta
        parser.add_argument(
            "--device_make", help="Specify device manufacturer. Note this input has precedence over the input read from the import source file.", default=None, required=False)
        parser.add_argument(
            "--device_model", help="Specify device model. Note this input has precedence over the input read from the import source file.", default=None, required=False)
        parser.add_argument(
            '--add_file_name', help="Add original file name to EXIF. Note this input has precedence over the input read from the import source file.", action='store_true', required=False)
        parser.add_argument(
            '--windows_path', help="If local file name is to be added with --add_file_name, added it as a windows path.", action='store_true', required=False)
        parser.add_argument(
            '--exclude_import_path', help="If local file name is to be added exclude import_path from the name.", action='store_true', required=False)
        parser.add_argument(
            "--exclude_path", help="If local file name is to be added, specify the path to be excluded.", default=None, required=False)
        parser.add_argument(
            '--add_import_date', help="Add import date.", action='store_true', required=False)
        parser.add_argument('--orientation', help='Specify the image orientation in degrees. Note this might result in image rotation. Note this input has precedence over the input read from the import source file.',
                            choices=[0, 90, 180, 270], type=int, default=None, required=False)
        parser.add_argument(
            "--GPS_accuracy", help="GPS accuracy in meters. Note this input has precedence over the input read from the import source file.", default=None, required=False)
        parser.add_argument(
            "--camera_uuid", help="Custom string used to differentiate different captures taken with the same camera make and model.", default=None, required=False)

        # geotagging
        parser.add_argument('--geotag_source', help='Provide the source of date/time and gps information needed for geotagging.', action='store',
                            choices=['exif', 'gpx', 'gopro_videos', 'nmea', 'blackvue_videos'], default="exif", required=False)
        parser.add_argument(
            '--geotag_source_path', help='Provide the path to the file source of date/time and gps information needed for geotagging.', action='store',
            default=None, required=False)
        parser.add_argument(
            '--local_time', help='Assume image timestamps are in your local time', action='store_true', default=False, required=False)
        parser.add_argument('--sub_second_interval',
                            help='Sub second time between shots. Used to set image times with sub-second precision',
                            type=float, default=0.0, required=False)
        parser.add_argument('--offset_time', default=0., type=float,
                            help='time offset between the camera and the gps device, in seconds.', required=False)
        parser.add_argument('--offset_angle', default=0., type=float,
                            help='offset camera angle (90 for right facing, 180 for rear facing, -90 for left facing)', required=False)
        parser.add_argument("--use_gps_start_time",
                            help="Use GPS trace starting time in case of derivating timestamp from filename.", action="store_true", default=False, required=False)

        # sequence
        parser.add_argument('--cutoff_distance', default=600., type=float,
                            help='maximum gps distance in meters within a sequence', required=False)
        parser.add_argument('--cutoff_time', default=60., type=float,
                            help='maximum time interval in seconds within a sequence', required=False)
        parser.add_argument('--interpolate_directions',
                            help='perform interploation of directions', action='store_true', required=False)
        parser.add_argument('--keep_duplicates',
                            help='keep duplicates, ie do not flag duplicates for upload exclusion, but keep them to be uploaded', action='store_true', required=False, default=False)
        parser.add_argument('--duplicate_distance',
                            help='max distance for two images to be considered duplicates in meters', type=float, default=0.1, required=False)
        parser.add_argument(
            '--duplicate_angle', help='max angle for two images to be considered duplicates in degrees', type=float, default=5, required=False)
        # EXIF insert
        parser.add_argument('--skip_EXIF_insert', help='Skip inserting the extracted data into image EXIF.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--keep_original', help='Do not overwrite original images, instead save the processed images in a new directory called "processed_images" located in .mapillary in the import_path.',
                            action='store_true', default=False, required=False)
        parser.add_argument(
            '--number_threads', help='Specify the number of upload threads.', type=int, default=None, required=False)
        parser.add_argument(
            '--max_attempts', help='Specify the maximum number of attempts to upload.', type=int, default=None, required=False)

        # post process
        parser.add_argument('--summarize', help='Summarize import for given import path.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--move_all_images', help='Move all images in import_path according to import state.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--move_duplicates', help='Move images in case they were flagged as duplicates.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--move_uploaded', help='Move images according to upload state.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--move_sequences', help='Move images into sequence folders.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--save_as_json', help='Save summary or file status list in a json.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--list_file_status', help='List file status for given import path.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--push_images', help='Push images uploaded in given import path.',
                            action='store_true', default=False, required=False)
        parser.add_argument(
            '--split_import_path', help='If splitting the import path into duplicates, sequences, success and failed uploads, provide a path for the splits.', default=None, required=False)
        parser.add_argument('--save_local_mapping', help='Save the mapillary photo uuid to local file mapping in a csv.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--overwrite_all_EXIF_tags', help='Overwrite the rest of the EXIF tags, whose values are changed during the processing. Default is False, which will result in the processed values to be inserted only in the EXIF Image Description tag.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--overwrite_EXIF_time_tag', help='Overwrite the capture time EXIF tag with the value obtained in process.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--overwrite_EXIF_gps_tag', help='Overwrite the gps EXIF tag with the value obtained in process.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--overwrite_EXIF_direction_tag', help='Overwrite the camera direction EXIF tag with the value obtained in process.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--overwrite_EXIF_orientation_tag', help='Overwrite the orientation EXIF tag with the value obtained in process.',
                            action='store_true', default=False, required=False)
        # add custom meta data in a form of a string consisting of a triplet
        # "name,type,value"
        parser.add_argument('--custom_meta_data', help='Add custom meta data to all images. Required format of input is a string, consisting of the meta data name, type and value, separated by a comma for each entry, where entries are separated by semicolon. Supported types are long, double, string, boolean, date. Example for two meta data entries "random_name1,double,12.34;random_name2,long,1234"',
                            default=None, required=False)

    def run(self, args):

        vars_args = vars(args)
        if "geotag_source" in vars_args and vars_args["geotag_source"] == 'blackvue_videos' and ("device_make" not in vars_args or ("device_make" in vars_args and not vars_args["device_make"])):
            vars_args["device_make"] = "Blackvue"
        if "device_make" in vars_args and vars_args["device_make"] and vars_args["device_make"].lower() == "blackvue":
            vars_args["duplicate_angle"] = 360

        process_user_properties(**({k: v for k, v in vars_args.iteritems()
                                    if k in inspect.getargspec(process_user_properties).args}))

        process_import_meta_properties(
            **({k: v for k, v in vars_args.iteritems() if k in inspect.getargspec(process_import_meta_properties).args}))

        process_geotag_properties(
            **({k: v for k, v in vars_args.iteritems() if k in inspect.getargspec(process_geotag_properties).args}))

        process_sequence_properties(
            **({k: v for k, v in vars_args.iteritems() if k in inspect.getargspec(process_sequence_properties).args}))

        process_upload_params(**({k: v for k, v in vars_args.iteritems()
                                  if k in inspect.getargspec(process_upload_params).args}))

        insert_MAPJson(**({k: v for k, v in vars_args.iteritems()
                           if k in inspect.getargspec(insert_MAPJson).args}))
        print("Process done.")

        upload(**({k: v for k, v in vars_args.iteritems()
                   if k in inspect.getargspec(upload).args}))

        post_process(**({k: v for k, v in vars_args.iteritems()
                         if k in inspect.getargspec(post_process).args}))
