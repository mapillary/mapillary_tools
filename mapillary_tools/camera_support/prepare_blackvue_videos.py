from pymp4.parser import Box
import io


def find_camera_model(videos_folder) -> bytes:
    from ..uploader import get_video_file_list

    file_list = get_video_file_list(videos_folder)
    if not file_list:
        raise RuntimeError(f"No video found in {videos_folder}")

    fd = open(file_list[0], "rb")

    fd.seek(0, io.SEEK_END)
    eof = fd.tell()
    fd.seek(0)
    while fd.tell() < eof:
        box = Box.parse_stream(fd)
        if box.type.decode("utf-8") == "free":  # or 'ftyp':
            return box.data[29:39]
    raise RuntimeError(f"camera model not found in {file_list[0]}")


def apply_config_blackvue(vars_args):
    model = find_camera_model(vars_args["video_import_path"])
    vars_args["device_model"] = model.decode("utf-8")
    vars_args["device_make"] = "Blackvue"
    vars_args["geotag_source"] = "blackvue_videos"
    vars_args["duplicate_angle"] = 360
    return vars_args
