<!--
Copyright (c) Meta Platforms, Inc. and affiliates.

This source code is licensed under the BSD license found in the
LICENSE file in the root directory of this source tree.
-->

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

See the [command reference](https://github.com/mapillary/mapillary_tools/blob/main/docs/command_reference.md) for what each command does, its options, and common pitfalls.

<!--ts-->

- [Supported File Formats](#supported-file-formats)
  - [Image Formats](#image-formats)
  - [Video Formats](#video-formats)
- [Installation](#installation)
  - [Standalone Executable](#standalone-executable)
  - [Installing via pip](#installing-via-pip)
    - [Installing on Android Devices](#installing-on-android-devices)
- [Usage](#usage)
  - [Process and Upload](#process-and-upload)
  - [Process](#process)
  - [Upload](#upload)
  - [Check Upload History](#check-upload-history)
- [Advanced Usage](#advanced-usage)
  - [Local Video Processing](#local-video-processing)
    - [Install FFmpeg](#install-ffmpeg)
    - [Video Processing](#video-processing)
  - [Geotagging with GPX](#geotagging-with-gpx)
  - [New video geotagging features (experimental)](#new-video-geotagging-features-experimental)
    - [Usage](#usage-1)
    - [Examples](#examples)
      - [Generic supported videos](#generic-supported-videos)
      - [External GPX](#external-gpx)
      - [Insta360 stitched videos](#insta360-stitched-videos)
    - [Limitations of `--video_geotag_source`](#limitations-of---video_geotag_source)
  - [Authenticate](#authenticate)
    - [Examples](#examples-1)
  - [Image Description](#image-description)
  - [Zip Images](#zip-images)
- [Development](#development)
  - [Setup](#setup)
    - [Option 1: Using uv (Recommended)](#option-1-using-uv-recommended)
    - [Option 2: Using pip with virtual environment](#option-2-using-pip-with-virtual-environment)
  - [Running the code](#running-the-code)
  - [Tests](#tests)
  - [Code Quality](#code-quality)
  - [Release and Build](#release-and-build)

<!--te-->

# Supported File Formats

mapillary_tools can upload both images and videos.

## Image Formats

mapillary_tools supports JPG/JPEG images (.jpg, .jpeg), with the following EXIF tags minimally required:

- GPS Longitude
- GPS Latitude
- Date/Time Original or GPS Date/Time

## Video Formats

mapillary_tools supports videos (.mp4, .360) that contain any of the following telemetry structures:

- [GPMF](https://github.com/gopro/gpmf-parser): mostly GoPro videos
  - [GoPro HERO series](https://gopro.com/en/us/shop/cameras/hero11-black/CHDHX-111-master.html) (from 5 to 13)
  - [GoPro MAX](https://gopro.com/en/us/shop/cameras/max/CHDHZ-202-master.html)
- [CAMM](https://developers.google.com/streetview/publish/camm-spec): an open-standard telemetry spec supported by a number of cameras
  - [Insta360 Pro2](https://www.insta360.com/product/insta360-pro2/)
  - [Insta360 Titan](https://www.insta360.com/product/insta360-titan)
  - [Ricoh Theta X](https://theta360.com/en/about/theta/x.html)
  - [Labpano](https://www.labpano.com/)
  - and more...
- [BlackVue](https://blackvue.com/) videos
  - [DR900S-1CH](https://shop.blackvue.com/product/dr900x-1ch-plus/)
  - [DR900X Plus](https://shop.blackvue.com/product/dr900x-2ch-plus/)
- Novatek-based dashcams, such as Viofo, Vantrue and Anker Roav dashcams

Other videos can be geotagged from the GPS that [ExifTool](https://exiftool.org/) reads, if it is installed,
or from a GPX or NMEA track recorded along with them (see [Geotagging with GPX](#geotagging-with-gpx)).

# Installation

## Standalone Executable

1. Download the latest executable for your platform from the [releases](https://github.com/mapillary/mapillary_tools/releases).
2. Move the executable to your system `$PATH`

> **_NOTE:_** If you see the error "**mapillary_tools is damaged and can’t be opened**" on macOS, try to clear the extended attributes:
>
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
pkg install python git build-essential libgeos openssl libjpeg-turbo libexpat libexpat-static
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

To upload to an organization by a name you saved for it, use `--organization_name` instead of `--organization_key`
(see [Upload](#upload)).

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
# Mark images within 3 meters of the previous one as duplicates.
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
    --cutoff_distance 100 \
    --cutoff_time 120
```

In a directory, files that are not supported images or videos are left out. A file named on the command line that
is not one fails, with a `MapillaryUnsupportedFileError` entry in the image description file, unless it is a
sidecar or companion file such as `.gpx`, `.xml` or `.thm`: those are skipped with a warning.

To write a JSON report of the files found, the unsupported files skipped and the warnings about the files processed,
specify `--process_report_path` (see the
[command reference](https://github.com/mapillary/mapillary_tools/blob/main/docs/command_reference.md#process) for its format):

```sh
mapillary_tools process MY_CAPTURE_DIR \
    --process_report_path /tmp/mapillary_process_report.json
```

## Upload

After processing you should get the [image description file](#image-description). Pass it to the `upload` command to upload them:

```sh
# Upload processed images and videos to the specified user account and organization
mapillary_tools upload  MY_CAPTURE_DIR \
    --desc_path /tmp/mapillary_image_description.json \
    --user_name "my_username" \
    --organization_key "my_organization_id"
```

To upload to an organization by a name instead of its ID, save a name for it once, with its ID.
The name is saved in the user profile in the config file:

```sh
# Upload to the organization, and save its ID under the name "work" in the profile "my_username"
mapillary_tools upload MY_CAPTURE_DIR \
    --desc_path /tmp/mapillary_image_description.json \
    --user_name "my_username" \
    --organization_key "my_organization_id" \
    --organization_name "work"

# From then on, upload to the organization by its name
mapillary_tools upload MY_CAPTURE_DIR \
    --desc_path /tmp/mapillary_image_description.json \
    --user_name "my_username" \
    --organization_name "work"
```

`--organization_name` works with `upload`, `process_and_upload` and `video_process_and_upload`.
A name is 2 to 32 letters, numbers, hyphens and underscores, starting with a letter, and it is case-sensitive.
Saving a name that is already saved with another ID replaces the ID.
To list or delete saved names, see [Authenticate](#authenticate).

Image sequences, videos and zip files that were uploaded from this computer before are skipped. Each is compared as a
whole: a sequence with one image added or removed is uploaded again. To upload them again anyway, specify
`--reupload`.

## Check Upload History

To check whether processed image sequences, videos or zip files were previously uploaded
from this device, use the same import paths and description file that would be
passed to `upload`:

```sh
mapillary_tools check_upload_history MY_CAPTURE_DIR \
    --desc_path /tmp/mapillary_image_description.json
```

It prints a JSON array with one entry per image sequence, video or zip file, which tells whether it was already
uploaded (see the
[command reference](https://github.com/mapillary/mapillary_tools/blob/main/docs/command_reference.md#check_upload_history)).
It reads only the local upload history: it needs no login, makes no network requests, and changes nothing.

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

If a video can not be sampled, for example because it has no GPS track to locate the frames along,
mapillary_tools still samples the other videos and processes their sample images, then exits with an error.
To skip such videos instead, specify `--skip_sample_errors`. It covers sampling only: errors from processing
the sample images are skipped with `--skip_process_errors`.

```sh
# Sample and process the videos that can be sampled, and skip the others
mapillary_tools video_process MY_VIDEO_DIR MY_SAMPLES --skip_sample_errors
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
It is used to locate the images along the GPS tracks. Images captured before the track starts, after it ends, or in a
gap of more than an hour between two of its points (such as between two trips in one GPX file) fall outside the track,
and are not geotagged from it. The same applies to videos. To allow longer gaps, set the environment variable
`MAPILLARY_TOOLS_MAX_GPX_GAP_SECONDS` (3600 by default).

Only the track points (`<trkpt>`) of a GPX file that have a time are read, not its routes or waypoints. A GPX file
in which no track point has a time that can be read fails with an error that says why.

```sh
mapillary_tools process MY_IMAGE_DIR --geotag_source "gpx" --geotag_source_path MY_EXTERNAL_GPS.gpx
```

To geotag videos with a GPX file, the sample images are located along the GPS track by the time they were captured.
A video whose own GPS records the time is synced to the track by that clock. For a video without one, specify its start
time, in UTC, with `--video_start_time`. That start time applies to every video in the command, so to place several
videos along one GPX file, run it once per video, each with its own start time:

```sh
mapillary_tools video_process MY_VIDEO.mp4 \
    --geotag_source "gpx" \
    --geotag_source_path MY_EXTERNAL_GPS.gpx \
    --video_start_time 2025_03_14_07_00_30_000
```

Without it, the track is assumed to start with the video. The creation time of a video, which comes from the camera's
clock, is never used to place a track. When the track lasts more than a minute longer or shorter than the video,
mapillary_tools warns: trim the GPX to the video, or specify `--video_start_time`.

A timelapse video packs several seconds of capture into each second of video. Its GPS clock, if it has one, tells how
many. If it has none, specify how many with `--video_duration_ratio`, for instance 60 for a timelapse that took a frame
every 2 seconds and plays at 30 frames per second:

```sh
mapillary_tools video_process MY_TIMELAPSE.mp4 \
    --geotag_source "gpx" \
    --geotag_source_path MY_EXTERNAL_GPS.gpx \
    --video_start_time 2025_03_14_07_00_30_000 \
    --video_duration_ratio 60
```

Ideally, the GPS device and the capture device should use the same clock to get the timestamps synchronized.
If not, as is often the case, the image locations will be shifted. To solve that, mapillary_tools provides an
option `--interpolation_offset_time N` that adds N seconds to image capture times for synchronizing the timestamps.

```sh
# The capture device's clock is 8 hours (i.e. -8 * 3600 = -28800 seconds) ahead of the GPS device's clock
mapillary_tools process MY_IMAGE_DIR \
    --geotag_source "gpx" \
    --geotag_source_path MY_EXTERNAL_GPS.gpx \
    --interpolation_offset_time -28800
```

The offset applies to videos geotagged from the GPX as well. In a directory that mixes images and videos, an offset
that corrects the camera clock of the images also moves the track of each video, and a video that the moved track
misses fails. To avoid that, process the images on their own with `--file_types image`.

Another option `--interpolation_use_gpx_start_time` moves your images to align with the beginning of the GPS track.
This is useful when you can confirm that you start GPS recording and capturing at the same time, or with a known delay.
For a video without a GPS clock, `video_process` then refuses a track that lasts more than twice as long as the video
spans at its `--video_duration_ratio`. If the GPS logger was left running after the video, pass the start of the
track as `--video_start_time` instead, which places the video the same way: the error prints it.

```sh
# Start capturing 2.5 seconds after start GPS recording
mapillary_tools video_process MY_VIDEO.mp4 \
    --geotag_source "gpx" \
    --geotag_source_path MY_EXTERNAL_GPS.gpx \
    --interpolation_use_gpx_start_time \
    --interpolation_offset_time 2.5
```

## New video geotagging features (experimental)

As experimental features, mapillary_tools can now:
* Geotag videos from tracks recorded in GPX and NMEA files
* Invoke `exiftool` internally, if available on the system. `exiftool` can extract geolocation data from a wide
range of video formats, allowing us to support more cameras with less trouble for the end user.
* Try several geotagging sources sequentially, until proper data is found.

These features apply to the `process` command, which analyzes the video for direct upload instead of sampling it
into images. They are experimental and will be subject to change in future releases.

### Usage

The new video processing is triggered with the `--video_geotag_source SOURCE` option. It can be specified multiple times:
In this case, each source will be tried in turn, until one returns good quality data.

`SOURCE` can be:
1. the plain name of the source - one of `native, video, camm, gopro, blackvue, gpx, nmea, exiftool_xml, exiftool_runtime`
2. a JSON object that includes optional parameters
```json5
{
  "source": "SOURCE",
  "pattern": "FILENAME_PATTERN" // optional
}
```

PATTERN specifies how the data source file is named, starting from the video filename:
* `%f`: the full video filename
* `%g`: the video filename without extension
* `%e`: the video filename extension

Supported sources and their default pattern are:

* `native`, or `video`: parse the video looking for geolocation in any format that mapillary_tools reads: GoPro, CAMM,
BlackVue and others. No pattern: it reads the video itself
* `camm`: parse the video looking for a CAMM track. No pattern
* `gopro`: parse the video looking for geolocation in GoPro format. No pattern
* `blackvue`: parse the video looking for geolocation in BlackVue format. No pattern
* `gpx`: external GPX file. Pattern: `%g.gpx`
* `nmea`: external NMEA file. Pattern: `%g.nmea`
* `exiftool_xml`: external XML file generated by exiftool. Pattern: `%g.xml`
* `exiftool_runtime`: execute exiftool on the video file. Pattern: `%f`

Notes:
* `exiftool_runtime` only works if exiftool is installed on the system. You can find it at https://exiftool.org/ or through
your software manager. If exiftool is installed, but is not in the default execution path, it is
possible to specify its location by setting the environment variable `MAPILLARY_TOOLS_EXIFTOOL_PATH`.
* Patterns are case-sensitive or not depending on the file system: `%g.gpx` matches both `basename.gpx` and
`basename.GPX` on Windows and, by default, on macOS, but not on Linux.
* If both `--video_geotag_source` and `--geotag_source` are specified, the `--video_geotag_source` sources are tried
first, on videos only, and the `--geotag_source` sources then geotag the images and the videos left. If only
`--video_geotag_source` is specified, image files (including the frames that `video_process` samples) are geotagged
by the default sources.

### Examples

#### Generic supported videos

Process all videos in a directory, trying to parse them as CAMM, GoPro or BlackVue:
```sh
mapillary_tools process --video_geotag_source video VIDEO_DIR/
```

#### External GPX

Process all videos in a directory, taking geolocation data from GPX files. A video named `foo.mp4` will be associated
with a GPX file called `foo.gpx`.
```sh
mapillary_tools process --video_geotag_source gpx VIDEO_DIR/
```
NMEA files work the same way with `--video_geotag_source nmea`, which associates `foo.mp4` with `foo.nmea`. What
follows about GPX tracks applies to NMEA tracks too.

#### Insta360 stitched videos

The videos to process have been stitched by Insta360 Studio; the geolocation data is in the original
videos in the parent directory, and there may be GPX files alongside the stitched video.
First look for GPX, then fallback to running exiftool against the original videos.
```sh
mapillary_tools process \
--video_geotag_source gpx \
--video_geotag_source '{"source": "exiftool_runtime", "pattern": "../%g.insv"}' \
VIDEO_DIR/
```

### Limitations of `--video_geotag_source`

**A GPX track is synced by the GPS clock of the video, if the video has GPS of its own, and otherwise aligned with
the start of the video.** A video without GPS of its own is assumed to start with the track, with a warning when the
track lasts more than a minute longer or shorter than the video: trim the GPX to the video, or sample the video with
`video_process` and `--video_start_time`. The track of a timelapse is expected to last longer, and is uploaded whole.

As with images, `--interpolation_offset_time N` adds N seconds to the time of the video to find its positions along
the GPX track, and `--interpolation_use_gpx_start_time` aligns the start of the video with the start of the track, even
if the video has GPS:

```sh
# Start recording the video 2.5 seconds after starting the GPS logger
mapillary_tools process VIDEO_DIR/ \
    --video_geotag_source gpx \
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

Authenticate for user `my_username`. If the user is already authenticated, it will update the credentials in the config:

```sh
mapillary_tools authenticate --user_name "my_username"
```

The command lists the existing profiles first, with the organization names saved in each of them
(see [Upload](#upload) to save one). Updating the credentials keeps the saved names.

Delete the organization name `work` saved in the profile `my_username`. The profile and its other saved names are kept:

```sh
mapillary_tools authenticate --user_name "my_username" --organization_name "work" --delete
```

## Image Description

The output of the [`process`](#process) command is a JSON array of objects that describes metadata for each image or video.
The metadata is validated by the [image description schema](https://github.com/mapillary/mapillary_tools/blob/main/schema/image_description_schema.json).
Here is a minimal example:

```json
[
  {
    "MAPLatitude": 58.5927694,
    "MAPLongitude": 16.1840944,
    "MAPCaptureTime": "2021_02_13_13_24_41_140",
    "filename": "/MY_IMAGE_DIR/IMG_0001.jpg"
  },
  {
    "error": {
      "type": "MapillaryGeoTaggingError",
      "message": "Unable to extract GPS Longitude or GPS Latitude from the image"
    },
    "filename": "/MY_IMAGE_DIR/IMG_0002.jpg"
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

The `zip` command writes each processed image sequence into a zip file, with the metadata in the images.
The `upload` command uploads zip files as they are, so they can be uploaded later.

```sh
# Zip processed images in MY_IMAGE_DIR and write zip files in MY_ZIPFILES
mapillary_tools zip MY_IMAGE_DIR MY_ZIPFILES

# Upload all the zip files (*.zip) in MY_ZIPFILES
mapillary_tools upload MY_ZIPFILES --desc_path MY_IMAGE_DIR/mapillary_image_description.json
```

# Development

## Setup

Clone the repository:

```sh
git clone git@github.com:mapillary/mapillary_tools.git
cd mapillary_tools
```

### Option 1: Using uv (Recommended)

Use [uv](https://docs.astral.sh/uv/) - a fast Python package manager.

Install the project in development mode with all dependencies:

```sh
# Install the project and development dependencies
uv sync --group dev

# Activate the virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### Option 2: Using pip with virtual environment

Set up a virtual environment (recommended):

```sh
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

Install the project in development mode:

```sh
# Install the project and all dependencies in editable mode
pip install -e .

# Install development dependencies
pip install --group dev
```

## Running the code

Run the code from the repository:

```sh
# If you have mapillary_tools installed in editable mode
mapillary_tools --version

# Alternatively
python -m mapillary_tools.commands --version
```

## Tests

Run tests:

```sh
# Test all cases
pytest -s -vv tests
# Or test a single case specifically
pytest -s -vv tests/unit/test_camm_parser.py::test_build_and_parse
```

## Code Quality

Run code formatting and linting:

```sh
# Format code with ruff
ruff format mapillary_tools tests

# Lint code with ruff
ruff check mapillary_tools tests

# Sort imports with usort
usort format mapillary_tools tests

# Type checking with mypy
mypy mapillary_tools
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
