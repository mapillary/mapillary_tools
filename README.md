[![Build Status](https://travis-ci.org/mapillary/mapillary_tools.svg?branch=master)](https://travis-ci.org/mapillary/mapillary_tools)

## Mapillary Tools

Mapillary tools is a library for processing and uploading geotagged images to Mapillary.

<!--ts-->
   * [Dependencies](#dependencies)
   * [Installation](#installation)
   * [Requirements](#requirements)
   * [Usage](#usage)
   * [Advanced Usage](#advanced-usage)
   * [Tool Specifications](#tool-specifications)
   * [Misc](#misc)
<!--te-->

## Dependencies

* [exifread]
* [gpxpy]
* [PIL]
* [Piexif]

Note that we're using a fork of the original [Piexif](https://github.com/hMatoba/Piexif), which needs to be installed separately. The rest of dependencies are installed along with the tools.


## Installation 

### Basic Setup

You will need to have [python=2.7.x](https://www.python.org/downloads/release/python-2715/), [pip>=10.0.1](https://pip.pypa.io/en/stable/installing/) and [git](https://git-scm.com/downloads) installed. Then you need to 

#### Install Piexif
`mapillary_tools` uses a fork of the original Piexif which needs to be installed by running:

	pip install git+https://github.com/mapillary/Piexif

#### Install Mapillary Tools

To install `mapillary_tools` on MacOSX, Ubuntu, or Windows, run:

	pip install --upgrade git+https://github.com/mapillary/mapillary_tools

which will enable processing and uploading of images. Note that the commands should either be run in [`virtualenv`](https://virtualenv.pypa.io/en/stable/installation/) or as `sudo`.

### Video Support

To sample images from videos, you will also need to install `ffmpeg`.

#### MacOSX

To install `ffmpeg` on Mac OS X use [Homebrew](https://brew.sh).
Once you have Homebrew installed, you can install `ffmpeg` by running:

```bash
brew install ffmpeg
```

#### Ubuntu

To install `ffmpeg` on Ubuntu:

```bash
sudo apt-get install ffmpeg
```

#### Windows

To install `ffmpeg` on Windows, follow these [instructions](http://adaptivesamples.com/how-to-install-ffmpeg-on-windows/).


## Requirements

### User Authentication

To upload images to Mapillary, an account is required and can be created [here](https://www.mapillary.com/signup). When using the upload tools for the first time, user authentication is required. You will be prompted to enter your account credentials.

### Metadata

To upload images to Mapillary, image `GPS` and `capture time` are minimally required. More information [here](https://help.mapillary.com/hc/en-us/articles/115001717829-Geotagging-images).

### Videos
To upload videos to Mapillary, videos are required to be sampled into images and tagged with image `GPS` and `capture time`. More information [here](https://help.mapillary.com/hc/en-us/articles/115001485045-Video-uploads).


## Usage

Upload tools can be used with the executable `mapillary_tools`, located in `mapillary_tools/mapillary_tools/bin`. 

### Execution
Running the executable `mapillary_tools` is slightly different on Unix and Windows OS.

#### Windows 
On Windows, the executable `mapillary_tools` is installed under the python's `Scripts` and needs to be inserted in the PATH manually.
At the same time, the interpreter program `python` needs to be specified, as the interpreter directive in the executable is specified for Unix OS. Path to the interpreter program `python` needs to be available in the PATH. Example of usage, in case `python` and `mapillary_tools` are available in the PATH: 

	python mapillary_tools

in case of issues with editing PATH, both `python` and `mapillary_tools` can be specified with the absolute path:

	C:\python27\python.exe C:\python27\Scripts\mapillary_tools
	
note that the location of the `python` interpreter program and scripts installed as `python` scripts can be different depending on the Windows and Python versions. Therefore users need to check the exact paths locally before running.

#### Unix
On Ubuntu and MacOSX the executable is available in the PATH after installation and can be used as is (no need to specify `python` as the interpreter program and no need for setting up the PATH or providing the absolute path to executable, no matter where in the command line you are located).
 


### Available tools

To see the available tools, use the following in the command line(for Windows, adjust the command according the instructions for execution):

```
mapillary_tools -h
```
Executable `mapillary_tools` takes the following arguments:

`-h, --help`: Show help and exit

`--advanced`: Use the tools under an advanced level, with additional arguments and tools available

`tool`: Use one of the available tools:

- `process`: Process the images including for instance, geotagging and sequence arrangement
- `upload`: Upload images to Mapillary
- `process_and_upload`: A bundled tool for `process` and `upload`

See the tool specific help for required and optional arguments:

 - Show help for `process` tool:

  ```bash
mapillary_tools process -h
```
 - Show advanced help for `process` tool:

  ```bash
mapillary_tools process -h --advanced
```


### Examples

For Windows, adjust the commands according the instructions for execution.

#### Process Images
The command below processes all images in the directory and its sub-directories. It will update the images with Mapillary-specific metadata in the image EXIF for the user with user name `mapillary_user`. It requires that each image in the directory contains `capture time` and `GPS`.

 ```bash
mapillary_tools process --import_path "path/to/images" --user_name "mapillary_user"
```

#### Upload Images
The command below uploads all images in a directory and its sub-directories. It requires Mapillary-specific metadata in the image EXIF. It works for images that are captured with Mapillary iOS or Android apps or processed with the `process` tool.

 ```bash
mapillary_tools upload --import_path "path/to/images"
```

#### Process and Upload Images
The command below runs `process` and `upload` consecutively for a directory.

```bash
mapillary_tools process_and_upload --import_path "path/to/images" --user_name "mapillary_user"
```


## Advanced Usage


Available tools for advanced usage:
- Video Specific Tools:
  - sample_video
  - video_process
  - video_process_and_upload
- Process Unit Tools:
  - extract_user_data
  - extract_import_meta_data
  - extract_geotag_data
  - extract_sequence_data
  - extract_upload_params
  - exif_insert
- Other Tools:
  - process_csv
  - interpolate
  - authenticate

### Geotag and Upload

 - Run process and upload consecutively, while process is reading geotag data from a gpx track. It requires that `capture time` information is embedded in the image EXIF. You can use 

 ```bash
mapillary_tools process --advanced --import_path "path/to/images" --user_name username_at_mapilary --geotag_source "gpx" --geotag_source_path "path/to/gpx_file"
mapillary_tools upload --import_path "path/to/images"
```

or

 ```bash
mapillary_tools process_and_upload --advanced --import_path "path/to/images" --user_name username_at_mapilary --geotag_source "gpx" --geotag_source_path "path/to/gpx_file"
```

### Keep original images intact and Upload

 - To prevent data loss or control versions, the original images can be left intact by specifying the flag `--keep_original`. This will result in the edited image being saved in a copy of the original image, instead of the original image itself. Copies are saved in `{$import_path/$image_path/}.mapilary/process_images}` and are deleted at the start of every processing run.
 
```bash
mapillary_tools process --advanced --import_path "path/to/images" --user_name username_at_mapilary --keep_original
mapillary_tools upload --import_path "path/to/images"
```

or

 ```bash
mapillary_tools process_and_upload --advanced --import_path "path/to/images" --user_name username_at_mapilary --keep_original
```


### Derive image direction, flag duplicates and Upload
 - Derive image direction (image heading or camera angle) based on image latitude and longitude and flag duplicates to be excluded from the upload. If images are missing direction, the direction is derived automatically, if direction is present, it will be derived and overwritten only if the flag `--interpolate directions` is specified.

 ```bash
mapillary_tools process --advanced --import_path "path/to/images" --user_name username_at_mapilary --flag_duplicates --interpolate_directions
mapillary_tools upload --import_path "path/to/images"
```

or

 ```bash
mapillary_tools process_and_upload --advanced --import_path "path/to/images" --user_name username_at_mapilary --flag_duplicates --interpolate_directions
```

### Video Sampling and Upload

 - Sample the video `path/to/video.mp4` into the directory `path/to/images`, at a sample interval of 0.5 seconds and tag the sampled images with `capture time`.

 ```bash
mapillary_tools sample_video --import_path "path/to/images" --video_file "path/to/video.mp4" --video_sample_interval 0.5 --advanced
```

 - Sample the video `path/to/video.mp4` into the directory `path/to/images`, at a sample interval of 2 seconds (default value) and tag the resulting images with `capture time`. And then process and upload the resulting images in `path/to/images` for user `username_at_mapilary`, specifying a gpx track to be the source of geotag data. 

```bash
mapillary_tools sample_video --import_path "path/to/images" --video_file "path/to/video.mp4"
mapillary_tools process --advanced --import_path "path/to/images" --user_name "username_at_mapilary" --geotag_source "gpx" --geotag_source_path "path/to/gpx_file"
mapillary_tools upload --import_path "path/to/images"
```

or

```bash
mapillary_tools video_process_and_upload --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --geotag_source "gpx" --geotag_source_path "path/to/gpx_file"
```

### Process csv
 - Insert image capture time and gps data from a csv file, based on filename:

```bash
mapillary_tools process_csv --import_path "path/to/images" --csv_path "path/to/csv_file" --filename_column 1 --timestamp_column 4 --latitude_column 2 --longitude_column 3 --advanced
```

 - Insert image capture time and meta data from a csv file based on the order of image file names (in case filename column is missing):
 
```bash
mapillary_tools process_csv --import_path "path/to/images" --csv_path "path/to/csv_file" --timestamp_column 1 --meta_columns "6,7" --meta_names "random_name1,random_name2" --meta_types "double,string" --advanced
```

## Tool Specifications


### `process`

The `process` tool will format the required and optional meta data into a Mapillary image description and insert it in the image EXIF. Images are required to contain image capture time, latitude, longitude and camera direction in the image EXIF. Under advanced usage, additional functionalities are available, for example latitude and longitude can be read from a gpx track file or a GoPro video, camera direction can be derived based on latitude and longitude, duplicates can be flagged to be excluded from the upload etc. See the tool specific help for required and optional arguments, add `--advanced` to see additional advanced optional arguments.

#### Examples

 - process all images for user `mapillary_user`, in the directory `path/to/images` and its sub-directories:

```bash
mapillary_tools process --import_path "path/to/images" --user_name "mapillary_user"
```
 - process all images for user `mapillary_user`, in the directory `path/to/images`, skipping the images in its sub-directories, rerunning process for all images that were not already uploaded and printing out extra warnings or errors.

```bash
mapillary_tools process --import_path "path/to/images" --user_name "mapillary_user" --verbose --rerun --skip_subfolders
```

#### Advanced Examples

 - Process all images for user `mapillary_user`, in the directory `path/to/images` and its sub-directories, reading geotag data from a gpx track stored in file `path/to/gpx_file`, specifying an offset of 2 seconds between the camera and gps device, ie, camera is 2 seconds ahead of the gps device and flagging images as duplicates in case they are apart by equal or less then the default 0.1 m and differ by the camera angle by equal or less than the default 5°.

```bash
mapillary_tools process --import_path "path/to/images" --user_name "mapillary_user" --advanced --geotag_source "gpx" --geotag_source_path "path/to/gpx_file" --offset_time 2 --flag_duplicates
```
 - Process all images for user `mapillary_user`, in the directory `path/to/images` and its sub-directories, specifying the import to be private imagery belonging to an organization with organization username `mapillary_organization`. You can find the organization username in your dashboard.

```bash
mapillary_tools process --import_path "path/to/images" --user_name "mapillary_user" --advanced --private --organization_username "mapillary_organization"
```
 - Process all images for user `mapillary_user`, in the directory `path/to/images` and its sub-directories, specifying an angle offset of 90° for the camera direction and splitting images into sequences of images apart by less than 100 meters according to image `GPS` and less than 120 seconds according to image `capture time`.

```bash
mapillary_tools process --import_path "path/to/images" --user_name "mapillary_user" --advanced --offset_angle 90 --cutoff_distance 100 --cutoff_time 120
```

### `upload`

Images that have been successfully processed or were taken with the Mapillary app will contain the required Mapillary image description embedded in the image EXIF and can be uploaded with the `upload` tool.

The `upload` tool will collect all the images in the import path, while checking for duplicate flags, processing and uploading logs.
If image is flagged as duplicate, was logged with failed process or logged as successfully uploaded, it will not be added to the upload list.

By default, 4 threads upload in parallel and the script retries 10 times upon encountering a failure. These can be customized with environment variables in the command line:

    NUMBER_THREADS=2
    MAX_ATTEMPTS=100

#### Examples

 - upload all images in the directory `path/to/images` and its sub directories:

```bash
mapillary_tools upload --import_path "path/to/images"
```

 - upload all images in the directory `path/to/images`, while skipping its sub directories and prompting the user to finalize the upload:

```bash
mapillary_tools upload --import_path "path/to/images" --skip_subfolders --manual_done
```

This tool has no additional advanced arguments.

### `process_and_upload`

`process_and_upload` tool will run `process` and `upload` tools consecutively with combined required and optional arguments.

#### Examples

- process and upload all the images in directory `path/to/images` and its sub-directories for user `mapillary_user`.

```bash
mapillary_tools process_and_upload --import_path "path/to/images" --user_name "mapillary_user"
```

#### Advanced Examples

- Process and upload all the images in directory `path/to/images` and its sub-directories for user `mapillary_user`, while skipping duplicate images. Here duplicate images are specified as consecutive images that are less than 0.5 meter apart according to image `GPS` and have less than 1° camera angle difference according to image direction.

```bash
mapillary_tools process_and_upload --import_path "path/to/images" --user_name "mapillary_user" --verbose --rerun --flag_duplicates --duplicate_distance 0.5 --duplicate_angle 1 --advanced
```

### `sample_video`

`sample_video` tool will sample a video into images and insert `capture time` to the image EXIF.
Capture time is calculated based on the `video start time` and sampling interval. Video start time can either be extracted from the video metadata or passed as an argument `--video_start_time` (milliseconds since UNIX epoch).


#### Examples

 - Sample the video `path/to/images` to directory `path/to/video` at the default sampling rate 2 seconds, ie 1 video frame every 2 seconds.

```bash
mapillary_tools sample_video --import_path "path/to/images" --video_file "path/to/video" --advanced
```

- Sample the video `path/to/images` to directory `path/to/video` at a sampling rate 0.5 seconds, ie two video frames every second and specifying the video start time to be `156893940910` (milliseconds since UNIX epoch).

```bash
mapillary_tools sample_video --import_path "path/to/images" --video_file "path/to/video" --video_sample_interval 0.5 --video_start_time 156893940910 --advanced
```

### `video_process`

`video_process` tool will run `video_sample` and `process` tools consecutively with combined required and optional arguments.

#### Examples

 - Sample the video `path/to/images` to directory `path/to/video` at the default sampling rate 2 seconds, ie 1 video frame every 2 seconds and process resulting video frames for user `mapillary_user`, reading geotag data from a GoPro video `path/to/gopro_video.mp4` and specifying to derive camera direction based on `GPS`.

```bash
mapillary_tools video_process --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --geotag_source "gopro_video" --geotag_source_path "path/to/gopro_video.mp4" --interpolate_directions
```

- In case video start capture time could not be extracted or specified, images should be tagged with `capture time` from the external geotag source, by passing the argument `--use_gps_start_time`. To make sure the external source and images are aligned ok, an offset in seconds can be specified.

```bash
mapillary_tools video_process --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --geotag_source "gpx" --geotag_source_path "path/to/gpx" --use_gps_start_time --offset_time 2
```

### `video_process_and_upload`

`video_process_and_upload` tool will run `video_sample`, `process` and `upload` tools consecutively with combined required and optional arguments.

#### Examples

 - Sample the video `path/to/images` to directory `path/to/video` at the default sampling rate 1 second, ie one video frame every second. Process and upload resulting video frames for user `mapillary_user`, reading geotag data from a gpx track stored in `path/to/gpx_file` video, assuming video start time can be extracted from the video file and deriving camera direction based on `GPS`.

```bash
mapillary_tools video_process_and_upload --import_path "path/to/images" --video_file "path/to/video" --user_name "mapillary_user" --advanced --geotag_source "gpx" --geotag_source_path "path/to/gpx_file" --video_sample_interval 1 --interpolate_directions
```

### Process Unit Tools

Process unit tools are tools executed by the `process` tool. Usage of process unit tools requires the flag `--advanced` to be passed and might require some experience with the upload tools.

#### `extract_user_data`

`extract_user_data` will process user specific properties and initialize authentication in case of first import. Credentials are then stored in a global config file and read from there in further imports.

#### `extract_import_meta_data`

`extract_import_meta_data` will process import specific meta data which is not required, but can be very useful. Import meta data is read from EXIF and/or can be passed through additional arguments.

#### `extract_geotag_data`

`extract_geotag_data` will process image capture date/time, latitude, longitude and camera angle. By default geotag data is read from image EXIF. Under advanced usage, a different source of latitude, longitude and camera direction can be specified. Geotagging can be adjusted for better quality, by specifying an offset angle for the camera direction or an offset time between the camera and gps device.

#### `extract_sequence_data`

`extract_sequence_data` will process the entire set of images located in the import path and create sequences, initially based on the file system structure, then based on image capture time and location and in the end splitting sequences longer than 500 images. Optionally, duplicates can be flagged (ie marked to be skipped when uploading) and camera directions can be  derived based on latitude and longitude.

#### `extract_upload_params`

`extract_upload_params` will process user specific upload parameters, required to safely upload images to Mapillary.

#### `exif_insert`

`exif_insert` will take all the meta data read and processed in the other processing unit tools and insert it in the image EXIF.


### Other Tools


#### `authenticate`

`authenticate` will update the user credentials stored in `/.config/mapillary/config` for the specified user_name.

#### `interpolate`

`interpolate` will interpolate identical timestamps in an csv file or stored in image EXIF or will interpolate missing gps data in a set of otherwise geotagged images.

#### `process_csv`

`process_csv` will parse the specified csv file and insert data in the image EXIF.


## Troubleshooting

In case of any issues with the installation and usage of `mapillary_tools`, check this section in case it has already been addressed, otherwise, open an issue on Github.

#### General
 - In case of any issues, it is always safe to try and rerun the failing command while specifying `--verbose` to see more information printed out. Uploaded images should not get uploaded more than once and should not be processed after uploading. The tool should take care of that, if it occurs otherwise, please open an issue on Github.
 - Make sure you run the latest version of `mapillary_tools`, which you can check with `mapillary_tools --version`. When installing the latest version, dont forget you need to specify `--upgrade`.
 - Advanced user are encouraged to explore the processed data and log files in the `{image_path}/.mapillary/logs/{image_name}/` to get more insight in the failure.
 
#### Execution
 - Windows users sometimes have trouble with the bare execution of `mapillary_tools`, since it is not inserted in the PATH automatically.
 If you are trying to execute `mapillary_tools` on Windows and dont have its path inserted in the PATH, make sure you execute the installed executable under Pythons scripts, for example `C:\python27\Scripts`. Due to the Python package naming convention, the package and the directory with the modules are also called `mapillary_tools`, so users often mistakenly try to run those instead of the executable called `mapillary_tools`, located in `mapillary_tools/mapillary_tools/bin`.
 
#### Run time issues
 - HTTP Errors can occur due to poor network connection or high load on the import pipeline. In most cases the images eventually get uploaded regardless. But in some cases HTTP Errors can occur due to authentication issues, which can be resolved by either removing the config file with the users credentials, located in `~/.config/mapillary/config` or running the `authenticate` command available under advanced usage of `mapillary_tools`.
 - Missing required data is often the reason for failed uploads, especially if the processing included parsing external data like a gps trace. Images are aligned with a gps trace based on the image capture time and gps time, where the default assumption is that both are in UTC. Check the begin and end date of your capture and the begin and end date of the gps trace to make sure that the image capture time is in the scope of the gps trace. To correct any offset between the two capture times, you can specify `--offset_time "offset time"`.
 Timezone differences can result in such issues, if you know that the image capture time was stored in your current local timezone, while the gps trace is stored in UTC, specify `--local_time`. If images do not contain capture time or the capture time is unreliable, while gps time is accurate, specify `use_gps_start_time`.
 - In cases where the `import_path` is located on an external mount, images can potentially get overwritten, if breaking the script with Ctrl+c. To keep the images intact, you can specify `--keep_original` and all the processed data will be inserted in a copy of the original image. We are still in progress of improving this step of data import and will make sure that no image gets overwritten at any point.

#### Upload quality issues
 - Some devices do not store the camera direction properly, often storing only 0. Camera direction will get derived based on latitide and longitude only if the camera direction is not set or `--interpolate_directions` is specified. Before processing and uploading images, make sure that the camera direction is either correct or missing and in case it is present but incorrect, you specify `-interpolate_directions`.
 - Timestamp interpolation is required in case the latitude and longitude are stored in an external gps trace with a higher capture frequency then the image capture frequency which results in identical image capture times. Command `interpolate` can be used to interpolate image capture time:
 
```bash
mapillary_tools interpolate --data "identical_timestamps" --import_path "path/to/images --advanced 
 ```

## Misc

### Download

The script below downloads images using the Mapillary image search API. Images can be downloaded inside a rectangle/bounding box, specifying the minimum and maximum latitude and longitude.


#### `download_images.py`

```bash
python download_images.py min_lat max_lat min_lon max_lon [--max_results=(max_results)] [--image_size=(320, 640, 1024, or 2048)]
```



[exifread]: https://pypi.python.org/pypi/ExifRead

[gpxpy]: https://pypi.python.org/pypi/gpxpy

[PIL]: https://pypi.python.org/pypi/Pillow/2.9.0

[Piexif]: https://github.com/mapillary/Piexif


