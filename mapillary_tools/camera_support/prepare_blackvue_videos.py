import io
import sys


def find_camera_model(videos_folder):
    from mapillary_tools.uploader import get_video_file_list

    file_list = get_video_file_list(videos_folder)

    fd = open(file_list[0], 'rb')

    fd.seek(0, io.SEEK_END)
    eof = fd.tell()
    fd.seek(0)
    from pymp4.parser import Box
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

def get_blackvue_info(video_file):
    with open(video_file,'rb') as f:
        response={}
        response['is_Blackvue_video']=False
        first_bytes = f.read(150)
        video_details = first_bytes.split(';')
        #Check if file is Blackvue video
        for idx, detail in enumerate(video_details):
            if 'Pittasoft' in detail:
                response['is_Blackvue_video']=True
                details_start = idx
        if response['is_Blackvue_video']==False:
            return response
        response['header'] = video_details[details_start+0]
        response['model_info'] = video_details[details_start+1]
        response['firmware_version']  = video_details[details_start+2]
        response['language'] = video_details[details_start+3]
        #Firmwares before 1.004 don't have a separate field for front and back, just a long string.
        #Assuming that first byte represents front and back
        if int(video_details[details_start+4][0])==1:
            response['camera_direction'] = 'Front'
        elif int(video_details[details_start+4][0])==2:
            response['camera_direction'] = 'Back'
        try:
            # Check that string is actually the SN, it could be missing since some firmwares don't output it
            if video_details[details_start+5][0:2]==response['model_info'][0:2]:
                response['serial_number'] = video_details[details_start+5]
            else:
                response['serial_number'] = None
        except:
            response['serial_number'] = None
    return response
