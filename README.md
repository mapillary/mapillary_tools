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
   
   
### on MacOSX


	pip install git+https://github.com/mapillary/mapillary_tools 


### on Ubuntu


	pip install git+https://github.com/mapillary/mapillary_tools 



### on Windows

	pip install git+https://github.com/mapillary/mapillary_tools 
	
**video specific installment**

In case of video sampling, `ffmpeg` has to be installed. 
  
Requirements
=============  

### User requirements

To import images to Mapillary, an account* is required and can be created [here](https://www.mapillary.com). 

*When using the import tools for the first time, user authentication is required. You will be prompted to enter your account email and password.

### Image and video requirements

Images are required to contain embedded Mapillary image description in the image EXIF. More information [here](https://help.mapillary.com/hc/en-us/articles/115001717829-Geotagging-images). 

In case images were captured with the Mapillary app, this requirement is met and images can be uploaded, otherwise Mapillary image description needs to be inserted in the image EXIF with the help of the `process` tool. For images to be processed successfully, image capture time is always required in the image EXIF. Latitude, longitude and camera direction are also required in the image EXIF, but can, under advanced usage, be read from external sources, or derived in case of camera direction.
Videos require sampling into images with the help of the `sample_video` advanced tool, prior processing and uploading.

Usage  
=============   

Import tools can be used with the executable `mapillary_import`, available in the PATH after installment. To see the available tools, type the following in the command line:

```bash 
mapillary_import --help
```
Executable `mapillary_import` takes the following arguments:

`-h, --help` show help and exit

`--advanced` use the tools under an advanced level, with additional arguments and tools available

`tool` one of the available Mapillary import tools

Available tools:
- main tools:
   - process
   - upload
- batch tools:
   - process_and_upload
   
The main tools are used to complete the entire pipeline of image import. To go through the entire pipeline main tools need to be run consecutively in the right order, batch tools can be used to do this easier. Each tool takes specific required and optional arguments. The list of available optional arguments is longer under advanced.

### Usage examples:

 - process all images in the directory `path/to/images` and its sub directories, resulting in Mapillary image description embedded in the image EXIF for user with user name `mapillary_user`. Requires that the image EXIF contains image capture date and time, latitude, longitude and camera direction, ie heading.
 
 ```bash 
	mapillary_import process --import_path "path/to/images" --user_name "mapillary_user"
```
 
 - upload all images in the directory `path/to/images` and its sub directories. Mapillary image description required in the image EXIF, resulting either from capturing the image with the app or from processing it with the `process` tool.

 ```bash 
    mapillary_import upload --import_path "path/to/images"
```

 - run process and upload consecutively.
 
```bash  
    mapillary_import process_and_upload --import_path "path/to/images" --user_name "mapillary_user"
```

   
   
### Advanced usage

Available tools under advanced usage:
- video specific tools:
   - main tools:
   		- sample_video
   - batch tools:
	   - video_process
	   - video_process_and_upload
- process unit tools:
   - extract_user_data
   - extract_import_meta_data
   - extract_geotag_data
   - extract_sequence_data
   - extract_upload_params
   - exif_insert

#### Advanced usage examples:

##### using additional advanced arguments

 - run process and upload consecutively, while process is reading geotag data from a gpx track. Requires that images contain capture time embedded in the image EXIF.
 
 ```bash 
    	mapillary_import process --advanced --import_path "path/to/images" --user_name username_at_mapilary --gps_source "gpx" --gps_source_path "path/to/gpx_file" 
    	mapillary_import upload --import_path "path/to/images"
```

or

 ```bash 	
	mapillary_import process_and_upload --advanced --import_path "path/to/images" --user_name username_at_mapilary --gps_source "gpx" --gps_source_path "path/to/gpx_file" 
```


##### using additional advanced tools

 - sample the video `path/to/video.mp4` into the directory `path/to/images`, at a sample interval 0.5 seconds.
 
 ```bash 
    mapillary_import sample_video --import_path "path/to/images" --video_file "path/to/video.mp4" --sample_interval 0.5 --advanced
```

 - sample the video `path/to/video.mp4` into the directory `path/to/images`, at a sample interval 2 seconds(default value) and run process and upload consecutively, while process* is reading geotag data from a gpx track.
 
```bash  
	mapillary_import sample_video --import_path "path/to/images" --video_file "path/to/video.mp4"
	mapillary_import process --advanced --import_path "path/to/images" --user_name username_at_mapilary --gps_source "gpx" --gps_source_path "path/to/gpx_file" 
	mapillary_import upload --import_path "path/to/images"
```

or

 ```bash 	
	mapillary_import video_process_and_upload --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --gps_source "gpx" --gps_source_path "path/to/gpx_file"
```
*Capture time inserted in the image EXIF while sampling, based on the video start capture time and sampling rate. If video start capture time can not be extracted, it can be passed as an argument `--video_start_time "start time in epoch(milliseconds)"`, otherwise video start capture time is set to current timestamp, which requires that `--use_gps_start_time` is passed to the process` tool, which will add an offset to the images so that gpx track and video capture start time are the same. To make sure the gpx track and the images are aligned ok, an offset in seconds can be specified as `--offset_time 2`.


Tool specifications 
=============  

## Main tools

### process

`process` tool will format the required and optional meta data into a Mapillary image description and insert it in the image EXIF. Images are required to contain image capture time, latitude, longitude and camera direction in the image EXIF. Under advanced usage, latitude and longitude can be read from a gpx track file or a GoPro video, while camera direction can be derived based on latitude and longitude.

See the tool specific help for required and optional arguments, add `--advanced` to see additional advanced optional arguments. Examples:

	mapillary_import process -h
	mapillary_import process -h --advanced
		
#### Usage examples:   

    mapillary_import process --import_path "path/to/images" --user_name "mapillary_user"
    mapillary_import process --import_path "path/to/images" --user_name "mapillary_user" --verbose --rerun --skip_subfolders

#### Advanced usage examples:   


### upload

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

### sample_video

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

## Batch tools

### process_and_upload

`process_and_upload` tool will run `process` and `upload` tools consecutively with combined required and optional arguments.

Usage examples:   

    mapillary_import process_and_upload --import_path "path/to/images" --user_name "mapillary_user"
    mapillary_import process_and_upload --import_path "path/to/images" --user_name "mapillary_user" --verbose --rerun --skip_subfolders

### video_process

`video_process` tool will run `video_sample` and `process` tools consecutively with combined required and optional arguments.

Usage examples:   

    mapillary_import video_process --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --gps_source "gpx" --gps_source_path "path/to/gpx_file"
    
### video_process_and_upload

`video_process_and_upload` tool will run `video_sample`, `process` and `upload` tools consecutively with combined required and optional arguments.

Usage examples: 
  
    mapillary_import video_process_and_upload --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --gps_source "gpx" --gps_source_path "path/to/gpx_file"

## Process unit tools

### extract_user_data

	TBD
	
### extract_import_meta_data

	TBD
	
### extract_geotag_data

	TBD

### extract_sequence_data

	TBD

### extract_upload_params

	TBD

### exif_insert**

	TBD

### sample_video**


Other
=============  

## Download

Download images from Mapillary.

Below script downloads images using the Mapillary image search API. Images can be downloaded inside a rectangle/bounding box, specifying the minimum and maximum latitude and longitude.

  
### download_images.py

```bash  
    python download_images.py min_lat max_lat min_lon max_lon [--max_results=(max_results)] [--image_size=(320, 640, 1024, or 2048)]
```

## Config

Edit a config file.  

User authentication is required to import images to Mapillary. When importing for the first time, user is prompted for user credentials and authentication logs are stored in a global config file for future authentication.

If you wish to manually edit a config file, the below script can be used.  
The defualt config file is your global Mapillary config file and will be used if no other file path provided.  

  
### edit_config.py 

```bash  
	python edit_config.py
	python edit_config.py "path/to/config_file"
```

[exifread]: https://pypi.python.org/pypi/ExifRead

[gpxpy]: https://pypi.python.org/pypi/gpxp

[PIL]: https://pypi.python.org/pypi/Pillow/2.2.

[Piexif]: https://github.com/mapillary/Piexif
