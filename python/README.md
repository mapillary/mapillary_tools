Python Tools for Mapillary
=============

## Dependencies

* [exifread]
* [gpxpy]
* [PIL]

## Installing on MacOSX
    sudo pip install -r requirements.txt

If you don't have pip on your system, you can install it by `sudo easy_install pip`.

## Preprocessing
Use these scripts to process your photos before uploading to improve the upload quality.

**add_fix_dates.py**

Script for adding dates to jpg files extracted from video with no tags. if you have a directory of files
provide the directory, the datetime for the first file, and an increment in seconds. For example, if the photos are
taken every 2 seconds, you can use

    python add_fix_dates.py path-to-images/ '2014-11-27 13:01:01' 2


**add_mapillary_tag_from_exif.py**

Script for uploading images taken with other cameras than the Mapillary iOS or Android apps.
Adds Mapillary data to EXIF tag to enable image to be handled in the same way as Mapillary
native images.

    python add_mapillary_tag_from_exif path-to-images/ [sequence_id]

(Requires environment variables set: MAPILLARY_USERNAME, MAPILLARY_EMAIL or MAPILLARY_PASSWORD)

**add_project.py**

Writes the project tokens to the EXIF of images in the given path. This way, you can add photos to a project programmatically. Use like this:

    python add_project.py path-to-images/ project_name

(Requires enviroment variables set: MAPILLARY_USERNAME, MAPILLARY_PASSWORD)

**geotag_from_gpx.py**

A lightweight script for geotagging images with GPS data from a gpx file. Writes lat, lon, and bearing to the right EXIF tags. Use it like:

    python geotag_from_gpx.py path-to-images/ gpx_file --time-offset [time_offset]

The time_offset is optional and is used if your camera clock is offset from your GPS clock. (Requires gpxpy, e.g. 'pip install gpxpy').


**interpolate_direction.py**

Interpolates the direction of an image based on the coordinates stored in
the EXIF tag of the next image in a set of consecutive images.

    python interpolate_direction.py path-to-images/ --offset_angle [offset_angle]


**remove_duplicates.py**

Supports the work flow of an action camera, by moving images taken too close together into another folder. This is for example when waiting for a green light. Images with bad or unrealistic exif data is moved to an error folder. Run using:

    python remove_duplicates.py [-d min-distance-meters] src-path/ [duplicate-path/]

Run with -h to see all options. Requires either the PIL or Pillow package to be installed. Pillow is newest and is the only one which will be supported in the future. Install using pip install Pillow or see http://pillow.readthedocs.org/.


**sequence_split.py**

This script organizes images into sequence groups based on a cutoff distance (in meters) and a cutoff time (in seconds). This is useful as a step before uploading lots of photos with the manual uploader. For example:

    python sequence_split.py path-to-images/ cutoff_distance [cutoff_time]

If no cutoff time is given, it will be estimated based on the between-photo differences.


## Upload

Use the upload script that suits your photos best.

**upload.py**

This script uploads images taken with any of the Mapillary apps to the Mapillary backend. Just run:

    python upload.py path-to-images/

To upload multiple sequences at once use the following syntax with the additional arguement:

    python upload.py path-to-images/ --upload_subfolders

On Android Systems you can find the images under `/storage/emulated/0/Android/data/app.mapillary/files/pictures/`.

On iOS, open iTunes, select your device, and scroll down to Mapillary under apps. You can see the files and copy them over from there.


**upload_with_authentication.py**

Script for uploading images taken with other cameras than the Mapillary apps. You can upload as:

    python upload_with_authentication.py path-to-images/

See this [blog post](http://blog.mapillary.com/technology/2014/07/21/upload-scripts.html) for more details.

If upload fails mid-sequence due to connection failure or similar, you should manually push the images to the server by opening [Manual Uploads](https://legacy.mapillary.com/map/upload/im) and pressing "push to Mapillary".

(Requires environment variables set:  MAPILLARY_USERNAME, MAPILLARY_PERMISSION_HASH, MAPILLARY_SIGNATURE_HASH from [upload from script information](https://www.mapillary.com/app/settings/developers))

**upload_with_preprocessing.py**

Script for preprocessing and uploading images taken with other cameras than
the Mapillary iOS or Android apps.

    python upload_with_preprocessing.py path-to-images/

It runs in the following steps:

- Skip images that are potential duplicates (optional with --remove_duplicates)
- Group images into sequences based on gps and time
- Interpolate compass angles for each sequence
- Add Mapillary tags to the images
- Upload the images

(Requires environment variables set:  MAPILLARY_USERNAME, MAPILLARY_PERMISSION_HASH, MAPILLARY_SIGNATURE_HASH from [upload from script information](https://www.mapillary.com/app/settings/developers))

## Download

Download images from Mapillary.

**download_images.py**

Script to download images using the Mapillary image search API. Downloads images inside a rect (min_lat, max_lat, min_lon, max_lon).

    download_images.py min_lat max_lat min_lon max_lon [--max_results=(max_results)] [--image_size=(320, 640, 1024, or 2048)]


**download_gpx_from_sequences.py**

this scripts is a fast way to download  GPS traces from the sequences uploaded to mapillary. Download traces inside a rect (min_lat, max_lat, min_lon, max_lon).
   
    python download_gpx_from_sequences.py min_lat max_lat min_lon max_lon [max_results] [filter_by_user_name]

**join_gpx_mapillary_files.py**

a fast way to join a lot of GPX files downloaded from mapillary if you use download_gpx_from_sequences.py , this is your second step for join  all in just one file. 

    python join_gpx_mapillary_files.py [gpx_directory] [outputfile.gpx]


[exifread]: https://pypi.python.org/pypi/ExifRead
[gpxpy]: https://pypi.python.org/pypi/gpxpy
[PIL]: https://pypi.python.org/pypi/Pillow/2.2.1
