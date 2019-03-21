
from mapillary_tools import process_video
from mapillary_tools.process_geotag_properties import (
    add_geotag_arguments,
    process_geotag_properties)


class Command:
    name = 'extract_geotag_data'
    help = "Process unit tool : Extract and process time and location properties."

    def add_basic_arguments(self, parser):
        pass

    def add_advanced_arguments(self, parser):
        add_geotag_arguments(parser)

    def run(self, args):
        vars_args=vars(args)
        if "geotag_source" in vars_args and vars_args["geotag_source"] == 'blackvue_videos' and ("device_make" not in vars_args or ("device_make" in vars_args and not vars_args["device_make"])):
            vars_args["device_make"] = "Blackvue"
        if "device_make" in vars_args and vars_args["device_make"] and vars_args["device_make"].lower() == "blackvue":
            vars_args["duplicate_angle"] = 360
        process_geotag_properties(**vars(args))
