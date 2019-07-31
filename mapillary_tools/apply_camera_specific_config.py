def apply_camera_specific_config(vars_args):
    # Check for Blackvue
    if "device_make" in vars_args and vars_args['device_make'].lower()=='blackvue' or "geotag_source" in vars_args and vars_args["geotag_source"] == 'blackvue_videos':
        from camera_support import prepare_blackvue_videos
        vars_args = prepare_blackvue_videos.apply_config_blackvue(vars_args)
    # Potentially check for other cameras i.e. Garmin
    return vars_args