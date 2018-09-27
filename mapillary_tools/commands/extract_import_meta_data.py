
from mapillary_tools.process_import_meta_properties import process_import_meta_properties


class Command:
    name = 'extract_import_meta_data'
    help = "Process unit tool: Extract and process import meta properties."

    def add_basic_arguments(self, parser):
        parser.add_argument(
            '--rerun', help='rerun the processing', action='store_true', required=False)
        parser.add_argument(
            '--skip_subfolders', help='Skip all subfolders and import only the images in the given directory path.', action='store_true', default=False, required=False)

    def add_basic_arguments(self, parser):

        # command specific args
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
        parser.add_argument(
            "--camera_uuid", help="Custom string used to differentiate different captures taken with the same camera make and model.", default=None, required=False)
        parser.add_argument('--custom_meta_data', help='Add custom meta data to all images. Required format of input is a string, consisting of the meta data name, type and value, separated by a comma for each entry, where entries are separated by semicolon. Supported types are long, double, string, boolean, date. Example for two meta data entries "random_name1,double,12.34;random_name2,long,1234"',
                            default=None, required=False)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):

        process_import_meta_properties(**vars(args))
