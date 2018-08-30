import inspect
from mapillary_tools.process_user_properties import process_user_properties
from mapillary_tools.process_import_meta_properties import process_import_meta_properties
from mapillary_tools.process_geotag_properties import process_geotag_properties
from mapillary_tools.process_sequence_properties import process_sequence_properties
from mapillary_tools.process_upload_params import process_upload_params
from mapillary_tools.insert_MAPJson import insert_MAPJson
from mapillary_tools.process_video import sample_video
from mapillary_tools.upload import upload


class Command:
    name = 'video_process_and_upload'
    help = "Batch tool : Sample video into images, process images and upload to Mapillary."

    def add_basic_arguments(self, parser):
        parser.add_argument(
            '--rerun', help='rerun the processing', action='store_true', required=False)
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
        # video specific args
        parser.add_argument('--video_file', help='Provide the path to a video file or a directory containing a set of Blackvue video files.',
                            action='store', default=None, required=False)
        parser.add_argument('--video_sample_interval',
                            help='Time interval for sampled video frames in seconds', default=2, type=float, required=False)
        parser.add_argument("--video_duration_ratio",
                            help="Real time video duration ratio of the under or oversampled video duration.", type=float, default=1.0, required=False)
        parser.add_argument("--video_start_time", help="Video start time in epochs (milliseconds)",
                            type=int, default=None, required=False)
        parser.add_argument(
            '--manual_done', help='Manually finalize the upload', action='store_true', default=False, required=False)
        parser.add_argument(
            '--skip_subfolders', help='Skip all subfolders and import only the images in the given directory path.', action='store_true', default=False, required=False)

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
            '--add_import_date', help="Add import date.", action='store_true', required=False)
        parser.add_argument('--orientation', help='Specify the image orientation in degrees. Note this might result in image rotation. Note this input has precedence over the input read from the import source file.',
                            choices=[0, 90, 180, 270], type=int, default=None, required=False)
        parser.add_argument(
            "--GPS_accuracy", help="GPS accuracy in meters. Note this input has precedence over the input read from the import source file.", default=None, required=False)

        # geotagging
        parser.add_argument('--geotag_source', help='Provide the source of date/time and gps information needed for geotagging.', action='store',
                            choices=['exif', 'gpx', 'gopro_video', 'nmea', 'blackvue'], default="exif", required=False)
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
        parser.add_argument('--flag_duplicates',
                            help='flag duplicates', action='store_true', required=False)
        parser.add_argument('--duplicate_distance',
                            help='max distance for two images to be considered duplicates in meters', type=float, default=0.1, required=False)
        parser.add_argument(
            '--duplicate_angle', help='max angle for two images to be considered duplicates in degrees', type=float, default=5, required=False)
        # EXIF insert
        parser.add_argument('--skip_EXIF_insert', help='Skip inserting the extracted data into image EXIF.',
                            action='store_true', default=False, required=False)
        parser.add_argument('--keep_original', help='Do not overwrite original images, instead save the processed images in a new directory by adding suffix "_processed" to the import_path.',
                            action='store_true', default=False, required=False)
        parser.add_argument(
            '--number_threads', help='Specify the number of upload threads.', type=int, default=None, required=False)
        parser.add_argument(
            '--max_attempts', help='Specify the maximum number of attempts to upload.', type=int, default=None, required=False)

    def run(self, args):

        vars_args = vars(args)

        sample_video(**({k: v for k, v in vars_args.iteritems()
                         if k in inspect.getargspec(sample_video).args}))

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

        upload(**({k: v for k, v in vars_args.iteritems()
                   if k in inspect.getargspec(upload).args}))
