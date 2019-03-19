from pymp4.parser import Box
import io
import sys

from mapillary_tools.uploader import get_video_file_list

def find_camera_model(videos_folder):
    file_list = get_video_file_list(videos_folder)

    fd = open(file_list[0], 'rb')

    fd.seek(0, io.SEEK_END)
    eof = fd.tell()
    fd.seek(0)
    while fd.tell() < eof:
        try:
            box = Box.parse_stream(fd)
        except RangeError:
            print('error parsing blackvue GPS information, exiting')
            sys.exit(1)
        except ConstError:
            print('error parsing blackvue GPS information, exiting')
            sys.exit(1)

        if box.type.decode('utf-8') == 'free':# or 'ftyp':     
            return box.data[29:39]

def apply_config_blackvue(vars_args):
    vars_args["device_model"]=find_camera_model(vars_args["video_import_path"])
    vars_args["device_make"]='Blackvue'
    vars_args["geotag_source"] = 'blackvue_videos'
    vars_args["duplicate_angle"] = 360
    return vars_args