import os


def set_video_as_uploaded(video):
    current_base_path = os.path.dirname(video)
    new_base_path = os.path.join(current_base_path, "uploaded")

    if not os.path.exists(new_base_path):
        os.mkdir(new_base_path)

    # Move video to uploaded folder
    new_video_path = os.path.join(new_base_path, os.path.basename(video))
    os.rename(video, new_video_path)

    # Move GPX file
    basename = os.path.basename(video)
    video_key = os.path.splitext(basename)[0]
    gpx_filename = f"{video_key}.gpx"
    gpx_path = os.path.join(current_base_path, gpx_filename)
    new_gpx_path = os.path.join(new_base_path, gpx_filename)
    os.rename(gpx_path, new_gpx_path)
