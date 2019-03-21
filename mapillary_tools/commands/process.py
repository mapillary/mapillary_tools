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
from mapillary_tools.post_process import (
    add_post_process_arguments,
    post_process)


class Command:
    name = 'process'
    help = 'Main tool : Process image meta data and insert it in image EXIF.'

    def add_basic_arguments(self, parser):
        add_user_arguments(parser)
        add_organization_arguments(parser)

    def add_advanced_arguments(self, parser):
        add_mapillary_arguments(parser)
        add_import_meta_arguments(parser)
        add_geotag_arguments(parser)
        add_sequence_arguments(parser)
        add_EXIF_insert_arguments(parser)
        add_post_process_arguments(parser)

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

        post_process(**({k: v for k, v in vars_args.iteritems()
                         if k in inspect.getargspec(post_process).args}))
