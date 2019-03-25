import inspect
from mapillary_tools.process_user_properties import (
    add_user_arguments,
    add_organization_arguments,
    add_mapillary_arguments,
    process_user_properties)
from mapillary_tools.process_import_meta_properties import (
    add_import_meta_arguments,
    process_import_meta_properties)
from mapillary_tools.process_geotag_properties import (
    add_geotag_arguments,
    process_geotag_properties)
from mapillary_tools.process_sequence_properties import (
    add_sequence_arguments,
    process_sequence_properties)
from mapillary_tools.process_upload_params import process_upload_params
from mapillary_tools.insert_MAPJson import (
    add_EXIF_insert_arguments,
    insert_MAPJson)
from mapillary_tools.upload import (
    add_upload_arguments,
    upload)
from mapillary_tools.post_process import post_process


class Command:
    name = 'process_and_upload'
    help = "Batch tool : Process images and upload to Mapillary."

    def add_basic_arguments(self, parser):
        add_user_arguments(parser)
        add_organization_arguments(parser)

    def add_advanced_arguments(self, parser):
        add_mapillary_arguments(parser)
        add_import_meta_arguments(parser)
        add_geotag_arguments(parser)
        add_sequence_arguments(parser)
        add_EXIF_insert_arguments(parser)
        add_upload_arguments(parser)

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
