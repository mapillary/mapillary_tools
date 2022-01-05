## Mapillary Tools

Mapillary Tools is a library for processing and uploading images to [Mapillary](https://www.mapillary.com/).

<!--ts-->

* [Quickstart](#quickstart)
* [Requirements](#requirements)
* [Installation](#installation)
* [Video Support](#video-support)
* [Usage](#usage)
    - [Process](#process)
    - [Upload Images](#upload-images)
    - [Upload BlackVue Videos](#upload-blackvue-videos)
    - [Video Process](#video-process)
    - [Authenticate](#authenticate)
    - [Aliases](#aliases)
* [Advanced Usage](#advanced-usage)
    - [Image Description](#image-description)
    - [Zip Images](#zip-images)
    - [Upload API](#upload-api)
* [Troubleshooting](#troubleshooting)
* [Development](#development)

<!--te-->

## Quickstart

Download the latest `mapillary_tools` binaries for your platform
here: https://github.com/mapillary/mapillary_tools/releases/tag/v0.8.1.
See [more installation instructions](#installation) below.

Process and upload imagery:

```shell
mapillary_tools process_and_upload "path/to/images/"
```

Upload BlackVue videos:

```shell
mapillary_tools upload "path/to/blackvue_videos/*.mp4"
```

## Requirements

### User Authentication

To upload images to Mapillary, an account is required and can be created [here](https://www.mapillary.com/signup). When
using the tools for the first time, user authentication is required. You will be prompted to enter your account
credentials.

### Metadata

To upload images to Mapillary, image `GPS` and `capture time` are minimally required. More
information [here](https://help.mapillary.com/hc/en-us/articles/115001717829-Geotagging-images).

## Installation

### Installing via Pip

Python (3.6 and above) and git are required:

```shell
python3 -m pip install --upgrade git+https://github.com/mapillary/mapillary_tools
```

If you see "Permission Denied" error, try to run the command above with `sudo`, or install it in your
local [virtualenv](#development) (recommended).

### Installing on Android Devices

A command line program such as Termux is required. Installation can be done without root privileges. The following
commands will install Python 3, pip3, git, and all required libraries for mapillary_tools on Termux:

```shell
pkg install python git build-essential libgeos openssl libjpeg-turbo
python3 -m pip install --upgrade pip wheel
python3 -m pip install --upgrade git+https://github.com/mapillary/mapillary_tools
```

Termux must access the device's internal storage to process and upload images. To do this, use the following command:

```shell
termux-setup-storage
```

Finally, on devices running Android 11, using a command line program, mapillary_tools will process images very slowly if
they are in shared internal storage during processing. It is advisable to first move images to the command line
program’s native directory before running mapillary_tools. For an example using Termux, if imagery is stored in the
folder `Internal storage/DCIM/mapillaryimages` the following command will move that folder from shared storage to
Termux:

```shell
mv -v storage/dcim/mapillaryimages mapillaryimages
```

## Video Support

To [process videos](#video-process), you will also need to install `ffmpeg`.

You can download `ffmpeg` from [here](https://ffmpeg.org/download.html). Make sure it is executable and put the
downloaded binaries in your `$PATH`. You can also install `ffmpeg` with your favourite package manager. For example:

On macOS, use [Homebrew](https://brew.sh/):

```shell
brew install ffmpeg
```

On Debian/Ubuntu:

```shell
sudo apt install ffmpeg
```

## Usage

### Process

The `process` command geotags images in the given directory. It extracts the required and optional metadata from image
EXIF (or the other supported geotag sources), and writes all the metadata (or process errors) in
an [image description](#image-description) file, which will be read during [upload](#upload).

#### Examples

Process all images in the directory `path/to/images/` (and its sub-directories):

```shell
mapillary_tools process "path/to/images/"
```

Interpolate images in the directory `path/to/images/` on the GPX track read from `path/to/gpx_file.gpx`. The images are
required to contain capture time in order to sort the images and interpolate them.

```shell
mapillary_tools process "path/to/images/" \
    --geotag_source "gpx" \
    --geotag_source_path "path/to/gpx_file.gpx"
```

Process all images in the directory, specifying an angle offset of 90° for the camera direction and splitting images
into sequences of images apart by less than 100 meters according to image `GPS` and less than 120 seconds according to
image capture time.

```shell
mapillary_tools process "path/to/images/" \
    --offset_angle 90 \
    --cutoff_distance 100 \
    --cutoff_time 120
```

### Upload Images

Images that have been successfully processed can be uploaded with the `upload` command.

#### Examples

Upload all processed images in the directory `path/to/images/` to user `mly_user` for organization `mly_organization_id`
. It is optional to specify `--user_name` if you have only one user [authenticated](#authenticate).

```shell
mapillary_tools upload "path/to/images/" \
    --user_name "mly_user" \
    --organization_key "mly_organization_id"
```

### Upload BlackVue Videos

BlackVue videos can be uploaded with the `upload` command and will be processed on Mapillary servers.

#### Examples

Upload a BlackVue video with file name `video_file_name.mp4` to user `mly_user` for organization `mly_organization_id`
. It is optional to specify `--user_name` if you have only one user [authenticated](#authenticate).

```shell
mapillary_tools upload "video_file_name.mp4" \
    --user_name "mly_user" \
    --organization_key "mly_organization_id"
```

### Video Process

Video process involves two commands:

1. `sample_video`: sample videos into images, and insert capture times to the image EXIF. Capture time is calculated
   based on the video start time and sampling interval. This is where `ffmpeg` is being used.
2. `process`: process (geotag) the sample images with the specified source

The two commands are usually combined into a single command `video_process`.

#### Examples

Sample the videos located in `path/to/videos/` at the default sampling rate 2 seconds, i.e. one video frame every two
seconds. Video frames will be sampled into a sub-directory `path/to/videos/mapillary_sampled_video_frames`.

```shell
mapillary_tools sample_video "path/to/videos/"
```

Sample the videos located in `path/to/videos/` to directory `path/to/sample_images/` at a sampling rate 0.5 seconds,
i.e. two video frames every second.

```shell
mapillary_tools sample_video "path/to/videos/" "path/to/sample_images/" \
    --video_sample_interval 0.5
```

Sample the videos located in `path/to/videos/` to the directory `path/to/sample_images/` at the default sampling rate 1
second, i.e. one video frame every second, geotagging data from a gpx track stored in `path/to/gpx_file.gpx` video,
assuming video start time can be extracted from the video file and deriving camera direction based on `GPS`.

```shell
mapillary_tools video_process "path/to/videos/" "path/to/sample_images/" \
    --geotag_source "gpx" \
    --geotag_source_path "path/to/gpx_file.gpx" \
    --video_sample_interval 1 \
    --interpolate_directions
```

**GoPro videos**: Sample GoPro videos in directory `path/to/videos/` into import path `path/to/sample_images/` at a
sampling rate 0.5 seconds, i.e. two frames every second, reading geotag data from the GoPro videos in `path/to/videos/`.

```shell
mapillary_tools video_process "path/to/videos/" "path/to/sample_images/" \
    --geotag_source "gopro_videos" \
    --interpolate_directions \
    --video_sample_interval 0.5
```

**BlackVue videos**: Sample BlackVue videos in directory `path/to/videos/` at a sampling rate 0.2 seconds, i.e. 5 frames
every second and process resulting video frames, reading geotag data from the BlackVue videos
in `path/to/videos/mapillary_sampled_video_frames`.

```shell
mapillary_tools video_process "path/to/videos/" \
    --geotag_source "blackvue_videos"
```

### Authenticate

The command `authenticate` will update the user credentials stored in the config file.

#### Examples

Authenticate new user:

```shell
mapillary_tools authenticate
```

Authenticate for user `mly_user`. If the user is already authenticated, it will update the credentials in the config:

```shell
mapillary_tools authenticate --user_name "mly_user"
```

### Aliases

#### `process_and_upload`

`process_and_upload` command will run `process` and `upload` commands consecutively with combined required and optional
arguments. It is equivalent to:

```shell
mapillary_tools process "path/to/images/"
mapillary_tools upload  "path/to/images/"
```

#### `video_process`

`video_process` command will run `sample_video` and `process` commands consecutively with combined required and optional
arguments. It is equivalent to:

```shell
mapillary_tools sample_video "path/to/videos/" "path/to/images/"
mapillary_tools upload "path/to/images/"
```

#### `video_process_and_upload`

`video_process_and_upload` command will run `sample_video` and `process_and_upload` commands consecutively with combined
required and optional arguments. It is equivalent to:

```shell
mapillary_tools sample_video "path/to/videos/" "path/to/videos/mapillary_sampled_video_frames/"
mapillary_tools process_and_upload "path/to/videos/mapillary_sampled_video_frames/"
```

## Advanced Usage

### Image Description

As the output, the `procss` command generates `mapillary_image_description.json` under the image directory by default.
The file contains an array of objects, each of which records the metadata of one image in the image directory. The
metadata is validated
by [the image description schema](https://github.com/mapillary/mapillary_tools/tree/master/schema/image_description_schema.json)
. Here is a minimal example:

```json
[
  {
    "MAPLatitude": 58.5927694,
    "MAPLongitude": 16.1840944,
    "MAPCaptureTime": "2021_02_13_13_24_41_140",
    "filename": "IMG_0291.jpg"
  },
  {
    "error": {
      "type": "MapillaryGeoTaggingError",
      "message": "Unable to extract GPS Longitude or GPS Latitude from the image"
    },
    "filename": "IMG_0292.jpg"
  }
]
```

The `upload` command then takes the image description file as the input, [zip images](#zip-images) with the specified
metadata, and then upload. The required `filename` property is used to associate images and metadata objects. Objects
that contain `error` property will be ignored.

#### Examples

Write and read the image description file in another location. This is useful if the image directory is readonly.

```shell
mapillary_tools process "path/to/images/" --desc_path "description.json"
mapillary_tools upload  "path/to/images/" --desc_path "description.json"
# equivalent to
mapillary_tools process_and_upload  "path/to/images/" --desc_path "description.json"
```

Edit the description file with your own scripts, e.g. filter out images outside a bounding box, or snap image locations
to the nearest roads:

```shell
mapillary_tools process "path/to/images/" --desc_path - \
    | ./filter_by_bbox.py 5.9559,45.818,10.4921,47.8084 \
    | ./map_match.py > "description.json"
mapillary_tools upload  "path/to/images/" --desc_path "description.json"
```

Geotag from a custom CSV format.

```shell
./custom_csv_to_description.sh special.csv | mapillary_tools upload "path/to/images/" --desc_path -
```

Geotag from a custom video format.

```shell
# sample with ffmpeg
ffmpeg -i "path/to/video.mp4" -vf fps=1/1 -qscale 1 -nostdin "path/to/images/video_%06d.jpg"
# extract geotags from the videos (or other sources)
./geotag_from_custom_video.sh "path/to/video.mp4" > "description.json"
# upload
mapillary_tools upload "path/to/images/" --desc_path "description.json"
```

### Zip Images

When [uploading](#upload) an image directory, internally the `upload` command will zip sequences in the temporary
directory (`TMPDIR`) and then upload these zip files.

Mapillary Tools provides `zip` command that allows users to specify where to store the zip files, usually somewhere with
faster IO or more free space.

#### Examples:

Zip processed images in `path/to/images/` and write zip files in `path/to/zipped_images/`:

```shell
mapillary_tools zip "path/to/images/" "path/to/zipped_images/"
```

Choose the image description file to write when zipping images:

```shell
mapillary_tools zip "path/to/images/" "path/to/zipped_images/" \
    --desc_path "path/to/image_description.json"
```

Then upload the zip files separately:

```shell
mapillary_tools upload path/to/zipped_images/*.zip
```

### Upload API

`mapillary_tools` provides a simple Upload API interface:

```python
class Uploader:
    def __init__(self, user_items: UserItem, emitter: EventEmitter = None, dry_run=False): ...

    def upload_zipfile(self, zip_path: str) -> Optional[int]: ...

    def upload_blackvue(self, blackvue_path: str) -> Optional[int]: ...

    def upload_images(self, descs: List[ImageDescriptionFile]) -> Dict[str, int]: ...
```

#### Examples

```python
import os
from mapillary_tools import uploader

# To obtain your user access token, check https://www.mapillary.com/developer/api-documentation/#authentication
user_item = {
    "user_upload_token": "YOUR_USER_ACCESS_TOKEN",
    "MAPOrganizationKey": 1234,
}
mly_uploader = uploader.Uploader(user_item)

descs = [
    {
        "MAPLatitude": 58.5927694,
        "MAPLongitude": 16.1840944,
        "MAPCaptureTime": "2021_02_13_13_24_41_140",
        "filename": "path/to/IMG_0291.jpg",
        "MAPSequenceUUID": "sequence_1",
    },
    {
        "MAPLatitude": 58.5927694,
        "MAPLongitude": 16.1840944,
        "MAPCaptureTime": "2021_02_13_13_24_41_140",
        "filename": "path/to/IMG_0292.jpg",
        "MAPSequenceUUID": "sequence_2",
    },
]

# Upload images as 2 sequences
mly_uploader.upload_images(descs)

# Zip images
uploader.zip_images(descs, "path/to/zip_dir")

# Upload zip files
for zip_path in os.listdir("path/to/zip_dir"):
    if zip_path.endswith(".zip"):
        mly_uploader.upload_zipfile(zip_path)

# Upload blackvue videos directly
mly_uploader.upload_blackvue("path/to/blackvue.mp4")
```

See more examples in
the [unit tests](https://github.com/mapillary/mapillary_tools/blob/main/tests/unit/test_uploader.py) or the upload
command [implementation](https://github.com/mapillary/mapillary_tools/blob/main/mapillary_tools/upload.py).

## Troubleshooting

In case of any issues with the installation and usage of `mapillary_tools`, check this section in case it has already
been addressed, otherwise, open an issue on GitHub.

### General

- In case of any issues, it is always safe to try and rerun the failing command while specifying `--verbose` to see more
  information printed out. Uploaded images should not get uploaded more than once and should not be processed after
  uploading. mapillary_tools should take care of that, if it occurs otherwise, please open an issue on GitHub.
- Make sure you run the latest version of `mapillary_tools`, which you can check with `mapillary_tools --version`. When
  installing the latest version, don't forget you need to specify `--upgrade`.
- Advanced user are encouraged to explore the processed data and the image description file in
  the `path/to/images/mapillary_image_description.json` to get more insight in the failure.

### Run time issues

- HTTP Errors can occur due to poor network connection or high load on the import pipeline. In most cases the images
  eventually get uploaded regardless. But in some cases HTTP Errors can occur due to authentication issues, which can be
  resolved by either removing the config file with the users credentials, located in `~/.config/mapillary/config` or
  running `mapillary_tools authenticate`.

- Missing required data is often the reason for failed uploads, especially if the processing included parsing external
  data like a gps trace. Images are aligned with a gps trace based on the image capture time and gps time, where the
  default assumption is that both are in UTC. Check the beginning and end date of your capture and the beginning and end
  date of the gps trace to make sure that the image capture time is in the scope of the gps trace. To correct any offset
  between the two capture times, you can specify `--offset_time "offset time"`.

### Upload quality issues

- Some devices do not store the camera direction properly, often storing only 0. Camera direction will get derived based
  on latitude and longitude only if the camera direction is not set or `--interpolate_directions` is specified. Before
  processing and uploading images, make sure that the camera direction is either correct or missing and in case it is
  present but incorrect, you specify `--interpolate_directions`.

## Development

Clone the repository:

```shell
git clone git@github.com:mapillary/mapillary_tools.git
cd mapillary_tools
```

Set up the virtual environment. It is optional but recommended:

```shell
python3 -m venv venv
source venv/bin/activate # For Windows, run: .\venv\Scripts\activate
# verify if the venv is activated
which python3
```

Install dependencies:

```shell
python3 -m pip install -r requirements.txt -r requirements-dev.txt
```

Run the code from the repository:

```shell
python3 -m mapillary_tools.commands --version
```

Run tests:

```shell
pytest tests
```

Run linting:

```shell
black mapillary_tools tests
```
