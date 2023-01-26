<p align="center">
  <a href="https://github.com/mapillary/mapillary_tools/">
    <img src="https://raw.githubusercontent.com/mapillary/mapillary_tools/main/docs/images/logo.png">
  </a>
</p>

<p align="center">
<a href="https://pypi.org/project/mapillary_tools/"><img alt="PyPI" src="https://img.shields.io/pypi/v/mapillary_tools"></a>
<a href="https://github.com/mapillary/mapillary_tools/actions"><img alt="Actions Status" src="https://github.com/mapillary/mapillary_tools/actions/workflows/python-package.yml/badge.svg"></a>
<a href="https://github.com/mapillary/mapillary_tools/blob/main/LICENSE"><img alt="GitHub license" src="https://img.shields.io/github/license/mapillary/mapillary_tools"></a>
<a href="https://github.com/mapillary/mapillary_tools/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/mapillary/mapillary_tools"></a>
<a href="https://pepy.tech/project/mapillary_tools"><img alt="Downloads" src="https://pepy.tech/badge/mapillary_tools"></a>
</p>

mapillary_tools is a command line tool that uploads geotagged images and videos to Mapillary.

```sh
# Install mapillary_tools
pip install mapillary_tools

# Process and upload images and videos in the directory
mapillary_tools process_and_upload MY_CAPTURE_DIR

# List all commands
mapillary_tools --help
```

<!--ts-->

- [Supported File Formats](#supported-file-formats)
- [Installation](#installation)
- [Usage](#usage)
  - [Process and Upload](#process-and-upload)
  - [Process](#process)
  - [Upload](#upload)
- [Advanced Usage](#advanced-usage)
  - [Local Video Processing](#local-video-processing)
  - [Authenticate](#authenticate)
  - [Image Description](#image-description)
  - [Zip Images](#zip-images)
- [Development](#development)

<!--te-->

# Supported File Formats

mapillary_tools can upload both images and videos.

## Image Formats

mapillary_tools supports JPG/JEPG images (.jpg, .jpeg), with the following EXIF tags minimally required:

- GPS Longitude
- GPS Latitude
- Date/Time Original or GPS Date/Time

## Video Formats

mapillary_tools supports videos (.mp4, .360) that contain any of the following telemetry structures:

- [GPMF](https://github.com/gopro/gpmf-parser): mostly GoPro videos
  - [GoPro HERO series](https://gopro.com/en/us/shop/cameras/hero11-black/CHDHX-111-master.html) (from 5 to 11)
  - [GoPro MAX](https://gopro.com/en/us/shop/cameras/max/CHDHZ-202-master.html)
- [CAMM](https://developers.google.com/streetview/publish/camm-spec): an open-standard telemetry spec supported by a number of cameras
  - [Insta360 Pro2](https://www.insta360.com/cn/product/insta360-pro2)
  - [Insta360 Titan](https://www.insta360.com/cn/product/insta360-titan)
  - [Ricoh Theta X](https://theta360.com/en/about/theta/x.html)
  - [Labpano](https://www.labpano.com/)
  - and more...
- [BlackVue](https://blackvue.com/) videos
  - [DR900S-1CH](https://shop.blackvue.com/product/dr900x-1ch-plus/)
  - [DR900X Plus](https://shop.blackvue.com/product/dr900x-2ch-plus/)

# Installation

## Standalone Executable

1. Download the latest executable for your platform from the [releases](https://github.com/mapillary/mapillary_tools/releases).
2. Move the executable to your system `$PATH`

> **_NOTE:_** If you see the error "**mapillary_tools is damaged and can’t be opened**" on macOS, run in your terminal:
> ```
> xattr -c mapillary_tools
> ```

## Installing via pip

To install or upgrade to the latest stable version:

```sh
pip install --upgrade mapillary_tools
```

If you can't wait for the latest features in development, install it from GitHub:

```sh
pip install --upgrade git+https://github.com/mapillary/mapillary_tools
```

> **_NOTE:_** If you see "**Permission Denied**" error, try to run the command above with `sudo`, or install it in your
> local [virtualenv](#setup) (recommended).

### Installing on Android Devices

A command line program such as Termux is required. Installation can be done without root privileges. The following
commands will install Python 3, pip3, git, and all required libraries for mapillary_tools on Termux:

```sh
pkg install python git build-essential libgeos openssl libjpeg-turbo
pip install --upgrade pip wheel
pip install --upgrade mapillary_tools
```

Termux must access the device's internal storage to process and upload images. To do this, use the following command:

```sh
termux-setup-storage
```

Finally, on devices running Android 11, using a command line program, mapillary_tools will process images very slowly if
they are in shared internal storage during processing. It is advisable to first move images to the command line
program’s native directory before running mapillary_tools. For an example using Termux, if imagery is stored in the
folder `Internal storage/DCIM/mapillaryimages` the following command will move that folder from shared storage to
Termux:

```sh
mv -v storage/dcim/mapillaryimages mapillaryimages
```

# Usage

## Process and Upload

For most users, `process_and_upload` is the command to go:

```sh
# Process and upload all images and videos in MY_CAPTURE_DIR and its subfolders, and all videos under MY_VIDEO_DIR
mapillary_tools process_and_upload MY_CAPTURE_DIR MY_VIDEO_DIR/*.mp4
```

If any process error occurs, e.g. GPS not found in an image, mapillary_tools will exit with non-zero status code.
To ignore these errors and continue uploading the rest:

```sh
# Skip process errors and upload to the specified user and organization
mapillary_tools process_and_upload MY_CAPTURE_DIR MY_VIDEO_DIR/*.mp4 \
    --skip_process_errors \
    --user_name "my_username" \
    --organization_key "my_organization_id"
```

The `process_and_upload` command will run the [`process`](#process) and the [`upload`](#upload) commands consecutively with combined required and optional arguments.
The command above is equivalent to:

```sh
mapillary_tools process MY_CAPTURE_DIR MY_VIDEO_DIR/*.mp4 \
    --skip_process_errors \
    --desc_path /tmp/mapillary_description_file.json

mapillary_tools upload MY_CAPTURE_DIR MY_VIDEO_DIR/*.mp4 \
    --desc_path /tmp/mapillary_description_file.json \
    --user_name "my_username" \
    --organization_key "my_organization_id"
```

## Process

The `process` command is an intermediate step that extracts the metadata from images and videos,
and writes them in an [image description file](#image-description). Users should pass it to the [`upload`](#upload) command.

```sh
mapillary_tools process MY_CAPTURE_DIR MY_VIDEO_DIR/*.mp4
```

Duplicate check with custom distance and angle:

```sh
# Mark images that are 3 meters closer to its previous one as duplicates.
# Duplicates won't be uploaded
mapillary_tools process MY_CAPTURE_DIR \
    --duplicate_distance 3 \
    --duplicate_angle 360  # Set 360 to disable angle check
```

Split sequences with the custom cutoff distance or custom capture time gap:

```sh
# If two successive images are 100 meters apart,
# OR their capture times are 120 seconds apart,
# then split the sequence from there
mapillary_tools process MY_CAPTURE_DIR \
    --offset_angle 90 \
    --cutoff_distance 100 \
    --cutoff_time 120 \
```

## Upload

After processing you should get the [image description file]((#image-description)). Pass it to the `upload` command to upload them:

```sh
# Upload processed images and videos to the specified user account and organization
mapillary_tools upload  MY_CAPTURE_DIR \
    --desc_path /tmp/mapillary_image_description.json \
    --user_name "my_username" \
    --organization_key "my_organization_id"
```

# Advanced Usage

## Local Video Processing

Local video processing samples a video into a sequence of sample images and ensures the images are geotagged and ready for uploading.
It gives users more control over the sampling process, for example, you can specify the sampling distance to control the density.
Also, the sample images have smaller file sizes than videos, hence saving bandwidth.

### Install FFmpeg

[FFmpeg](https://ffmpeg.org/) is required for local video processing.
You can download `ffmpeg` and `ffprobe` from [here](https://ffmpeg.org/download.html),
or install them with your favorite package manager.

### Video Processing

mapillary_tools first extracts the GPS track from the video's telemetry structure, and then locates video frames along the GPS track.
When all are located, it then extracts one frame (image) every 3 meters by default.

```sh
# Sample videos in MY_VIDEO_DIR and write the sample images in MY_SAMPLES with a custom sampling distance
mapillary_tools video_process MY_VIDEO_DIR MY_SAMPLES --video_sample_distance 5
# The command above is equivalent to
mapillary_tools sample_video MY_VIDEO_DIR MY_SAMPLES --video_sample_distance 5
mapillary_tools process MY_SAMPLES
```

To process and upload the sample images consecutively, run:

```sh
mapillary_tools video_process_and_upload MY_VIDEO_DIR MY_SAMPLES --video_sample_distance 5
# The command above is equivalent to
mapillary_tools video_process MY_VIDEO_DIR MY_SAMPLES --video_sample_distance 5 --desc_path=/tmp/mapillary_description.json
mapillary_tools upload MY_SAMPLES --desc_path=/tmp/mapillary_description.json
```

## Geotagging with GPX

If you use external GPS devices for mapping, you will need to geotag your captures with the external GPS tracks.

To geotag images with a GPX file, the capture time (extracted from EXIF tag "Date/Time Original" or "GPS Date/Time") is minimally required.
It is used to locate the images along the GPS tracks.

```sh
mapillary_tools process MY_IMAGE_DIR --geotag_source "gpx" --geotag_source_path MY_EXTERNAL_GPS.gpx
```

To geotag videos with a GPX file, video start time (video creation time minus video duration) is required to locate the sample images along the GPS tracks.

```sh
mapillary_tools video_process MY_VIDEO_DIR --geotag_source "gpx" --geotag_source_path MY_EXTERNAL_GPS.gpx
```

Ideally, the GPS device and the capture device need to use the same clock to get the timestamps synchronized.
If not, the image locations will be shifted, as is often the case (especially when you see `MapillaryOutsideGPXTrackError` errors).
To solve that, mapillary_tools provides an option `--interpolation_offset_time N` that adds N seconds to image capture times for synchronizing the timestamps.

```sh
# The capture device's clock is 8 hours ahead of the GPS device's clock
mapillary_tools process MY_IMAGE_DIR --geotag_source "gpx" --geotag_source_path MY_EXTERNAL_GPS.gpx \
    --interpolation_offset_time -28800 # -8 * 3600 seconds
```

Another option `--interpolation_use_gpx_start_time` moves your images to align with the beginning of the GPS track.
This is useful when you can confirm that you start GPS recording and capturing at the same time, or with a known delay.

```sh
# Start capturing 2.5 seconds after start GPS recording
mapillary_tools video_process MY_VIDEO_DIR --geotag_source "gpx" --geotag_source_path MY_EXTERNAL_GPS.gpx \
    --interpolation_use_gpx_start_time \
    --interpolation_offset_time 2.5
```

## Authenticate

The command `authenticate` will update the user credentials stored in the config file.

### Examples

Authenticate new user:

```sh
mapillary_tools authenticate
```

Authenticate for user `mly_user`. If the user is already authenticated, it will update the credentials in the config:

```sh
mapillary_tools authenticate --user_name "mly_user"
```

## Image Description

The output of the [`process`](#process) command is a JSON array of objects that describes metadata for each image or video.
The metadata is validated by the [image description schema](https://github.com/mapillary/mapillary_tools/tree/master/schema/image_description_schema.json).
Here is a minimal example:

```json
[
  {
    "MAPLatitude": 58.5927694,
    "MAPLongitude": 16.1840944,
    "MAPCaptureTime": "2021_02_13_13_24_41_140",
    "filename": "/MY_IMAGE_DIR/IMG_0291.jpg"
  },
  {
    "error": {
      "type": "MapillaryGeoTaggingError",
      "message": "Unable to extract GPS Longitude or GPS Latitude from the image"
    },
    "filename": "/MY_IMAGE_DIR/IMG_0292.jpg"
  }
]
```

Users may create or manipulate the image description file before passing them to the [`upload`](#upload) command. Here are a few examples:

```sh
# Remove images outside the bounding box and map matching the rest images on the road network
mapillary_tools process MY_IMAGE_DIR | \
    ./filter_by_bbox.py 5.9559,45.818,10.4921,47.8084  | \
    ./map_match.py > /tmp/mapillary_image_description.json

# Upload the processed images
mapillary_tools upload  MY_IMAGE_DIR --desc_path /tmp/mapillary_image_description.json
```

```sh
# Converts captures.csv to an image description file
./custom_csv_to_description.sh captures.csv | mapillary_tools upload MY_IMAGE_DIR --desc_path -
```

## Zip Images

When [uploading](#upload) an image directory, internally the `upload` command will zip sequences in the temporary
directory (`TMPDIR`) and then upload these zip files.

mapillary_tools provides `zip` command that allows users to specify where to store the zip files, usually somewhere with
faster IO or more free space.

```sh
# Zip processed images in MY_IMAGE_DIR and write zip files in MY_ZIPFILES
mapillary_tools zip MY_IMAGE_DIR MY_ZIPFILES

# Upload all the zip files (*.zip) in MY_ZIPFILES:
mapillary_tools upload MY_ZIPFILES
```

# Development

## Setup

Clone the repository:

```sh
git clone git@github.com:mapillary/mapillary_tools.git
cd mapillary_tools
```

Set up the virtual environment. It is optional but recommended:

```sh
pip install pipenv
```

Install dependencies:

```sh
pipenv install -r requirements.txt
pipenv install -r requirements-dev.txt
```

Enter the virtualenv shell:

```sh
pipenv shell
```

Run the code from the repository:

```sh
python3 -m mapillary_tools.commands --version
```

## Tests

Run tests:

```sh
# test all cases
python3 -m pytest -s -vv tests
# or test a single case specifically
python3 -m pytest -s -vv tests/unit/test_camm_parser.py::test_build_and_parse
```

Run linting:

```sh
# format code
black mapillary_tools tests
# sort imports
usort format mapillary_tools tests
```

## Release and Build

```sh
# Assume you are releasing v0.9.1a2 (alpha2)

# Tag your local branch
# Use -f here to replace the existing one
git tag -f v0.9.1a2

# Push the tagged commit first if it is not there yet
git push origin

# Push ALL local tags (TODO: How to push a specific tag?)
# Use -f here to replace the existing tags in the remote repo
git push origin --tags -f

# The last step will trigger CI to publish a draft release with binaries built
# in https://github.com/mapillary/mapillary_tools/releases
```
