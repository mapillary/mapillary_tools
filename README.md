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

Note that we're using a fork of [Piexif](https://github.com/hMatoba/Piexif) installed along with the tools as the rest of the dependencies.

  
Installing   
=============  
   
   
### MacOSX, Ubuntu, Windows


	pip install git+https://github.com/mapillary/mapillary_tools@mapillary_tools_v2

	
#### Video specific installment

In case of video sampling, `ffmpeg` has to be installed. 

##### MacOSX

To install `ffmpeg` on Mac OS X, use [Homebrew](https://brew.sh).
Once you have Homebrew installed, you can install `ffmpeg` by typing the following in the command line:

```bash
brew install ffmpeg
```

##### Ubuntu

To install `ffmpeg` on Ubuntu, please type the following in the command line: 

```bash
sudo apt-get install ffmpeg
```

##### Windows

To install `ffmpeg` on Windows, follow these [instructions](http://adaptivesamples.com/how-to-install-ffmpeg-on-windows/).

Requirements
=============  

### User requirements

To import images to Mapillary, an account is required and can be created [here](https://www.mapillary.com). When using the import tools for the first time, user authentication is required. You will be prompted to enter your account email and password.

### Image and video requirements

Images are required to contain embedded Mapillary image description in the image EXIF. More information [here](https://help.mapillary.com/hc/en-us/articles/115001717829-Geotagging-images). 

In case images were captured with the Mapillary app, this requirement is met and images can be uploaded, otherwise Mapillary image description needs to be inserted in the image EXIF with the help of the `process` tool. For images to be processed successfully, image capture time is always required in the image EXIF. Latitude, longitude and camera direction are also required in the image EXIF, but can, under advanced usage, be read from external sources, or derived in case of camera direction.
Videos require sampling into images with the help of the `sample_video` advanced tool, prior processing and uploading.

Usage  
=============   

Import tools can be used with the executable `mapillary_tools`, available in the PATH after installment. To see the available tools, type the following in the command line:

```bash 
mapillary_tools -h
```
Executable `mapillary_tools` takes the following arguments:

`-h, --help` show help and exit

`--advanced` use the tools under an advanced level, with additional arguments and tools available

`tool` one of the available Mapillary import tools

Available tools:
- process
- upload
- process_and_upload
   
`process` and `upload` tools are used to complete the entire pipeline of image import. To go through the entire pipeline `process` and `upload` need to be run consecutively in the right order, which is done with the`process_and_upload` tool. Each tool takes specific required and optional arguments. The list of available optional arguments is longer under advanced.

See the tool specific help for required and optional arguments:

 - show help for `process` tool:
 
  ```bash 	
mapillary_tools process -h
```
 - show advanced help for `process` tool:

  ```bash 	
mapillary_tools process -h --advanced
```

### Usage examples

 - process all images in the directory `path/to/images` and its sub directories, resulting in Mapillary image description embedded in the image EXIF for user with user name `mapillary_user`. Requires that the image EXIF contains image capture date and time, latitude, longitude and camera direction, ie heading.
 
 ```bash 
mapillary_tools process --import_path "path/to/images" --user_name "mapillary_user"
```
 
 - upload all images in the directory `path/to/images` and its sub directories. Mapillary image description required in the image EXIF, resulting either from capturing the image with the app or from processing it with the `process` tool.

 ```bash 
mapillary_tools upload --import_path "path/to/images"
```

 - run process and upload consecutively.
 
```bash  
mapillary_tools process_and_upload --import_path "path/to/images" --user_name "mapillary_user"
```

   
   
### Advanced usage

Available tools under advanced usage:
- video specific tools:
	- sample_video
	- video_process
	- video_process_and_upload
- process unit tools:
   - extract_user_data
   - extract_import_meta_data
   - extract_geotag_data
   - extract_sequence_data
   - extract_upload_params
   - exif_insert

#### Advanced usage examples

##### Using additional advanced arguments

 - run process and upload consecutively, while process is reading geotag data from a gpx track. Requires that images contain capture time embedded in the image EXIF.
 
 ```bash 
mapillary_tools process --advanced --import_path "path/to/images" --user_name username_at_mapilary --gps_source "gpx" --gps_source_path "path/to/gpx_file" 
mapillary_tools upload --import_path "path/to/images"
```

or

 ```bash 	
mapillary_tools process_and_upload --advanced --import_path "path/to/images" --user_name username_at_mapilary --gps_source "gpx" --gps_source_path "path/to/gpx_file" 
```


##### Using additional advanced tools

 - sample* the video `path/to/video.mp4` into the directory `path/to/images`, at a sample interval 0.5 seconds.
 
 ```bash 
mapillary_tools sample_video --import_path "path/to/images" --video_file "path/to/video.mp4" --sample_interval 0.5 --advanced
```

 - sample* the video `path/to/video.mp4` into the directory `path/to/images`, at a sample interval 2 seconds(default value) and run process and upload consecutively, while process is reading geotag data from a gpx track.
 
```bash  
mapillary_tools sample_video --import_path "path/to/images" --video_file "path/to/video.mp4"
mapillary_tools process --advanced --import_path "path/to/images" --user_name username_at_mapilary --gps_source "gpx" --gps_source_path "path/to/gpx_file" 
mapillary_tools upload --import_path "path/to/images"
```

or

 ```bash 	
mapillary_tools video_process_and_upload --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --gps_source "gpx" --gps_source_path "path/to/gpx_file"
```
*Capture time inserted in the image EXIF while sampling, based on the video start capture time and sampling rate. If video start capture time can not be extracted, it can be passed as an argument `--video_start_time "start time in epoch(milliseconds)"`, otherwise video start capture time is set to current timestamp, which requires that `--use_gps_start_time` is passed to the `process` tool, which will add an offset to the images so that gpx track and video capture start time are the same. To make sure the gpx track and the images are aligned ok, an offset in seconds can be specified as `--offset_time 2`.


Tool specifications 
=============  

## `process`

`process` tool will format the required and optional meta data into a Mapillary image description and insert it in the image EXIF. Images are required to contain image capture time, latitude, longitude and camera direction in the image EXIF. Under advanced usage, latitude and longitude can be read from a gpx track file or a GoPro video, while camera direction can be derived based on latitude and longitude.

See the tool specific help for required and optional arguments, add `--advanced` to see additional advanced optional arguments.
		
### Usage examples  

 - process all images for user `mapillary_user`, in the directory `path/to/images` and its sub-directories:
 
```bash 	   
mapillary_tools process --import_path "path/to/images" --user_name "mapillary_user"
```
 - process all images for user `mapillary_user`, in the directory `path/to/images`, skipping the images in its sub-directories, rerunning process for all images that were not already uploaded and printing out extra warnings or errors.

```bash 	   
mapillary_tools process --import_path "path/to/images" --user_name "mapillary_user" --verbose --rerun --skip_subfolders
```

### Advanced usage examples   

 - process all images for user `mapillary_user`, in the directory `path/to/images` and its sub-directories, reading geotag data from a gpx track stored in file `path/to/gpx_file`, specifying an offset of 2 seconds between the camera and gps device, ie, camera is 2 seconds ahead of the gps device and flagging images as duplicates in case they are apart by equal or less then the default 0.1 m and differ by the camera angle by equal or less than the default 5°.
 
```bash 	   
mapillary_tools process --import_path "path/to/images" --user_name "mapillary_user" --advanced --gps_source "gpx" --gps_source_path "path/to/gpx_file" --offset_time --flag_duplicates 
```
 - process all images for user `mapillary_user`, in the directory `path/to/images` and its sub-directories, specifying the import to belong to a private organization called `mapillary_organization`.

```bash 	   
mapillary_tools process --import_path "path/to/images" --user_name "mapillary_user" --advanced --private --organization_name "mapillary_organization"
```

## `upload`

Images that have been successfully processed or were taken with the Mapillary app will contain the required Mapillary image description embedded in the image EXIF and can be uploaded with the `upload` tool.  

The `upload` tool will collect all the images in the import path, while checking for duplicate flags, processing and uploading logs.  
If image is flagged as duplicate, was logged with failed process or logged as successfully uploaded, it will not be added to the upload list.   

By default, 4 threads upload in parallel and the script retries 10 times upon encountering a failure. These can be customized with environment variables in the command line:  

    NUMBER_THREADS=2 
    MAX_ATTEMPTS=100
  
### Usage examples

 - upload all images in the directory `path/to/images` and its sub directories:

```bash 	   
mapillary_tools upload --import_path "path/to/images" 
```

 - upload all images in the directory `path/to/images`, while skipping its sub directories and prompting the user to finalize the upload:

```bash 	   
mapillary_tools upload --import_path "path/to/images" --skip_subfolders --manual_done
```

This tool has no additional advanced arguments.

## `process_and_upload`

`process_and_upload` tool will run `process` and `upload` tools consecutively with combined required and optional arguments.

### Usage examples   

- process and upload all the images in directory `path/to/images` and its sub directories for user `mapillary_user`.

```bash 	   
mapillary_tools process_and_upload --import_path "path/to/images" --user_name "mapillary_user"
```

### Advanced usage examples   

- process and upload all the images in directory `path/to/images` and its sub directories for user `mapillary_user`, but skip duplicate images, specifying duplicates as images apart up to 0.5 m or with a camera angle difference up to 1°.

```bash
mapillary_tools process_and_upload --import_path "path/to/images" --user_name "mapillary_user" --verbose --rerun --flag_duplicates --duplicate_distance 0.5 --duplicate_angle 1 --advanced
```

## `sample_video`

`sample_video` tool will sample a video into images and insert capture time in the image EXIF. Capture time of sampled images is derived based on the video capture start time and sampling rate. In case video capture start time can not be obtained, current time is taken. 
This tool is an advanced tool and might require some experience with the import tools.
	
### Usage examples   

 - sample the video `path/to/images` to directory `path/to/video` at the default sampling rate 2 seconds, ie 1 one video frame every 2 seconds.
 
```bash
mapillary_tools sample_video --import_path "path/to/images" --video_file "path/to/video" --advanced
```

- sample the video `path/to/images` to directory `path/to/video` at a sampling rate 0.5 seconds, ie two video frames every second and specifying the video start time to be `156893940910` (epoch)milliseconds.

```bash
mapillary_tools sample_video --import_path "path/to/images" --video_file "path/to/video" --video_sample_interval 0.5 --video_start_time 156893940910
```

## `video_process`

`video_process` tool will run `video_sample` and `process` tools consecutively with combined required and optional arguments.

### Usage examples   

 - sample the video `path/to/images` to directory `path/to/video` at the default sampling rate 2 seconds, ie one video frame every 2 seconds and process resulting video frames for user `mapillary_user`, reading geotag data from a GoPro video `path/to/gopro_video.mp4` and specifying to align video frames and gpx track capture times, by using gps device start capture time.

```bash 	   
mapillary_tools video_process --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --gps_source "gopro_video" --gps_source_path "path/to/gopro_video.mp4" --use_gps_start_time
```

## `video_process_and_upload`

`video_process_and_upload` tool will run `video_sample`, `process` and `upload` tools consecutively with combined required and optional arguments.

### Usage examples 

 - sample the video `path/to/images` to directory `path/to/video` at the default sampling rate 1 second, ie one video frame every second. Process and upload resulting video frames for user `mapillary_user`, reading geotag data from a gpx track stored in `path/to/gpx_file` video, assuming video start time can be extracted from the video file.
  
```bash 	   
mapillary_tools video_process_and_upload --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --gps_source "gpx" --gps_source_path "path/to/gpx_file" --video_sample_interval 1
```

## Process unit tools

Process unit tools are tools executed by the `process` tool. Usage of process unit tools might require some experience with the import tools and requires the flag `--advanced` to be passed.

### `extract_user_data`

`extract_user_data` process unit tool will process user specific properties and initialize authentication in case of first import. Credentials are then stored in a global config file and read from there in further imports.  
	
### `extract_import_meta_data`

`extract_import_meta_data` process unit tool will process import specific meta data which is not required, but can be very useful. Import meta data is read from EXIF and/or can be passed through additional arguments.   
	
### `extract_geotag_data`

`extract_geotag_data` process unit tool will process image capture date/time, latitude, longitude and camera angle. By default geotag data is read from image EXIF. Under advanced usage, a different source of latitude, longitude and camera direction can be specified. Geotagging can be adjusted for better quality, by specifying an offset angle for the camera direction or an offset time between the camera and gps device.

### `extract_sequence_data`

`extract_sequence_data` process unit tool will process the entire set of images located in the import path and create sequences, initially based on the file system structure, then based on image capture time and location and in the end splitting sequences longer then 500 images. Optionally, duplicates can be flagged(ie marked to be skipped when uploading) and camera directions can be  derived based on latitude and longitude.   

### `extract_upload_params`

`extract_upload_params` process unit tool will process user specific upload parameters, required to safely upload images to Mapillary.

### `exif_insert`

`exif_insert` process unit tool will take all the meta data read and processed in the other processing unit tools and insert it in the image EXIF.  


Other
=============  

## Download

Download images from Mapillary.

Below script downloads images using the Mapillary image search API. Images can be downloaded inside a rectangle/bounding box, specifying the minimum and maximum latitude and longitude.

  
### `download_images.py`

```bash  
python download_images.py min_lat max_lat min_lon max_lon [--max_results=(max_results)] [--image_size=(320, 640, 1024, or 2048)]
```

## Config

Edit a config file.  

User authentication is required to import images to Mapillary. When importing for the first time, user is prompted for user credentials and authentication logs are stored in a global config file for future authentication.

If you wish to manually edit a config file, the below script can be used.  
The defualt config file is your global Mapillary config file and will be used if no other file path provided.  

  
### `edit_config.py`

```bash  
python edit_config.py
python edit_config.py "path/to/config_file"
```

[exifread]: https://pypi.python.org/pypi/ExifRead

[gpxpy]: https://pypi.python.org/pypi/gpxp

[PIL]: https://pypi.python.org/pypi/Pillow/2.2.

[Piexif]: https://github.com/mapillary/Piexif
