[![Build Status](https://travis-ci.org/mapillary/mapillary_tools.svg?branch=master)](https://travis-ci.org/mapillary/mapillary_tools)

Python Mapillary Import Tools
=============

Table of contents
=================

<!--ts-->
   * [Dependencies](#dependencies)
   * [Installing](#installing)
   * [Requirements](#requirements)   
   * [Usage](#usage)
   * [Tool specifications](#tool_specification)
   * [Other](#other)
<!--te-->


   
Dependencies  
=============  

* [exifread]
* [gpxpy]
* [PIL]
* [Piexif]

Note that we're using a fork of [Piexif](https://github.com/hMatoba/Piexif) installed along with the tools.

  
Installing   
=============  
   
   
**on MacOSX**


	pip install git+https://github.com/mapillary/mapillary_tools 


**on Ubuntu**


	pip install git+https://github.com/mapillary/mapillary_tools 



**on Windows**

	pip install git+https://github.com/mapillary/mapillary_tools 
	
**video specific installment**

In case of video sampling, `ffmpeg` has to be installed. 
  
Requirements
=============  

To import images to Mapillary, an account is required and can be created [here](https://www.mapillary.com). 

When using the import tools for the first time, user authentication is required. You will be prompted to enter your account email and password.

Images are required to contain embedded Mapillary image description in the image EXIF. More information [here](https://help.mapillary.com/hc/en-us/articles/115001717829-Geotagging-images). 

In case images were captured with the Mapillary app, this requirement is met and images can be uploaded. 

In other cases, Mapillary image description needs to be inserted in the image EXIF using the process tool.

Videos require sampling into images, before processing and uploading.

Usage  
=============   

Import tools can be used with the executable `mapillary_import`, available in the PATH after installment.

	usage: Mapillary import tool [-h] [--advanced] tool ...
	
`-h, --help` show help and exit

`--advanced` use the tools under an advanced level, with additional arguments and tools available

`tool` one of the available Mapillary import tools

Available tools:
- main tools:
   - upload
   - process
   - sample_video
- batch tools:
   - process_and_upload
   - video_process
   - video_process_and_upload
   
Available under advanced:
- process unit tools:
   - extract_user_data
   - extract_import_meta_data
   - extract_geotag_data
   - extract_sequence_data
   - extract_upload_params
   - exif_insert

The main tools are used to complete the entire pipeline of image and video import.
To go through the entire pipeline main tools need to be run consecutively in the right order, batch tools can be used to do this easier. 
Process unit tools are available for users experienced with Mapillary import tools.
Each tool takes specific required and optional arguments. The list of available optional arguments is longer under advanced.


**Simple usage examples:**

    mapillary_import upload --import_path "path/to/images"

Will upload all images in the directory `path/to/images` and its sub directories. Mapillary image description required in the image EXIF.

    mapillary_import process --import_path "path/to/images" --user_name "mapillary_user"
    
Will process all images in the directory `path/to/images` and its sub directories, resulting in Mapillary image description embedded in the image EXIF for user with user name `mapillary_user`. Requires that the image EXIF contains image capture date and time, latitude, longitude and camera direction, ie heading.

    mapillary_import sample_video --import_path "path/to/images" --video_file "path/to/video.mp4" --sample_interval 0.5

Will sample the video `path/to/video.mp4` into the directory `path/to/images`, at a sample interval 0.5 seconds.

    mapillary_import process_and_upload --import_path "path/to/images" --user_name "mapillary_user"

Will run process and upload consecutively.

**Advanced usage example:**

    	mapillary_import process --advanced --import_path "path/to/images" --user_name username_at_mapilary --gps_source "gpx" --gps_source_path "path/to/gpx_file" 
    	mapillary_import upload --import_path "path/to/images"

or
	
	mapillary_import process_and_upload --advanced --import_path "path/to/images" --user_name username_at_mapilary --gps_source "gpx" --gps_source_path "path/to/gpx_file" 
	
Will run process and upload consecutively, while process is reading geotag data from a gpx track. Requires that images contain capture time embedded in the image EXIF.

Tool specifications 
=============  

**Main tools**

**upload**

Images that have been successfully processed or were taken with the Mapillary app will contain the required Mapillary image description embedded in the image EXIF and can be uploaded with the `upload` tool.  

The `upload` tool will collect all the images in the import path, while checking for duplicate flags, processing and uploading logs.  
If image is flagged as duplicate, was logged with failed process or logged as successfully uploaded, it will not be added to the upload list.   

By default, 4 threads upload in parallel and the script retries 10 times upon encountering a failure. These can be customized with environment variables in the command line:  

    NUMBER_THREADS=2 
    MAX_ATTEMPTS=100

In case you wish to monitor and double check the progress you can manually finalize the upload by passing the `--manual_done` argument.
In case you do not wish to import images in the subfolders, you can skip them by passing the `--skip_subfolders` argument.

Required arguments are:   
- `--import_path --import_path "path/to/images"`   
    path to your images  
    value type string  
  
Optional arguments are:  
- `--manual_done`  
    set True to automatically finalize the upload
    default value False  
- `--skip_subfolders`  
    set True to skip all the images in subfolders
    default value False  
  
Usage examples:

    mapillary_import upload --import_path "path/to/images" 

Will upload all images in the directory `path/to/images` and its sub directories.
 
    mapillary_import upload --import_path "path/to/images" --skip_subfolders --manual_done

Will upload all images in the directory `path/to/images`, while skipping its sub directories and prompting the user to finalize the upload.

This tool has no additional advanced arguments.

**process**

`process` tool will format the required and optional meta data into a Mapillary image description and insert it in the image EXIF. 
  
Required arguments are:   
- `--import_path "path/to/images"`   
    path to images  
    value type string  
- `--user_name "mapillary_user"`   
    specify the user name used to create an account at Mapillary  
    value type string   
  
Optional arguments are:  
- `--verbose`  
    set True to print out additional information and warnings  
- `--skip_subfolders`  
    set True to skip all the images in subfolders
    default value False
- `--rerun`  
    set True to rerun the process
    default value False
    will only affect images which were not already uploaded
- `--organization_name "mapillary_organization_name"`
	specify the organization name for the import
	default value None  
- `--organization_key "mapillary_organization_key"`
	specify the organization key for the import
	default value None 
- `--private`
	set True for image privacy, ie import in a private repository
	default value False
	
Usage examples:   

    mapillary_import process --import_path "path/to/images" --user_name "mapillary_user"
    mapillary_import process --import_path "path/to/images" --user_name "mapillary_user" --verbose --rerun --skip_subfolders

This tool runs several process units, each with specific required and optional arguments.
This tool has additional advanced arguments, listed under each process unit tool below.

**sample_video**

`sample_video` tool will sample a video into images and insert capture time in the image EXIF. 
  
Required arguments are:   
- `--import_path "path/to/images"`   
    path to images  
    value type string  
- `--video_file "path/to/video"`   
    path to video file  
    value type string   
  
Optional arguments are:  
- `--video_sample_interval "video sample interval"` 
    specify the sampling rate of the video in seconds
    value type float
    default value 2 seconds  
- `--video_duration_ratio "video duration ratio"`  
    specify the adjustment factor for video over/under sampling
    value type float
    default value 1.0  
- `--video_start_time "video start time"`  
    specify video start time in epochs (milliseconds)
    value type integer
    default value None  
	
Usage examples:   

    mapillary_import sample_video --import_path "path/to/images" --video_file "path/to/video"
    mapillary_import sample_video --import_path "path/to/images" --video_file "path/to/video" --video_sample_interval 0.5 --video_start_time 156893940910

This tool has no additional advanced arguments.

**Batch tools**

**process_and_upload**
`process_and_upload` tool will run `process` and `upload` tools consecutively with combined required and optional arguments.

Usage examples:   

    mapillary_import process_and_upload --import_path "path/to/images" --user_name "mapillary_user"
    mapillary_import process_and_upload --import_path "path/to/images" --user_name "mapillary_user" --verbose --rerun --skip_subfolders

**video_process**
`video_process` tool will run `video_sample` and `process` tools consecutively with combined required and optional arguments.

Usage examples:   

    mapillary_import video_process --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --gps_source "gpx" --gps_source_path "path/to/gpx_file"
    
**video_process_and_upload**
`video_process_and_upload` tool will run `video_sample`, `process` and `upload` tools consecutively with combined required and optional arguments.

Usage examples: 
  
    mapillary_import video_process_and_upload --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --gps_source "gpx" --gps_source_path "path/to/gpx_file"

**Process unit tools**

**extract_user_data**

	TBD
	
**extract_import_meta_data**

	TBD
	
**extract_geotag_data**

	TBD

**extract_sequence_data**

	TBD

**extract_upload_params**

	TBD

**exif_insert**

	TBD

**sample_video**


Other
=============  

**Download**

Download images from Mapillary.

Below script downloads images using the Mapillary image search API. Images can be downloaded inside a rectangle/bounding box, specifying the minimum and maximum latitude and longitude.

  
**download_images.py**  

    python download_images.py min_lat max_lat min_lon max_lon [--max_results=(max_results)] [--image_size=(320, 640, 1024, or 2048)]

**Config**

Edit a config file.  

User authentication is required to import images to Mapillary. When importing for the first time, user is prompted for user credentials and authentication logs are stored in a global config file for future authentication.

If you wish to manually edit a config file, the below script can be used.  
The defualt config file is your global Mapillary config file and will be used if no other file path provided.  

  
**edit_config.py**  

	python edit_config.py
	python edit_config.py path

[exifread]: https://pypi.python.org/pypi/ExifRead

[gpxpy]: https://pypi.python.org/pypi/gpxp

[PIL]: https://pypi.python.org/pypi/Pillow/2.2.

[Piexif]: https://github.com/mapillary/Piexi
s
