Python tools for Mapillary
=============

**upload.py**

This script uploads images taken with any of the Mapillary apps to the Mapillary backend. Just run:

    python upload.py path-to-images/ 


On Android Systems you can find the images under `/storage/emulated/0/Android/data/app.mapillary/files/pictures/`.

On iOS, open iTunes, select your device, and scroll down to Mapillary under apps. You can see the files and copy them over from there.


**upload_with_authentication.py**

Script for uploading images taken with other cameras than the Mapillary apps. You need to set environment variables with your permission hashes, then you can upload as:

    python upload_with_authentication.py path

See this [blog post](http://blog.mapillary.com/technology/2014/07/21/upload-scripts.html) for more details.


**geotag_from_gpx.py**

A lightweight script for geotagging images with GPS data from a gpx file. Writes lat, lon, and bearing to the right EXIF tags. Use it like:

    python geotag_from_gpx.py path gpx_file time_offset

The time_offset is optional and is used if your camera clock is offset from your GPS clock. *This script needs testing with different images and gpx files. File issues if you find anything.*


**time_split.py**

This script organizes images into sequence groups based on a cutoff time. This is useful as a step before uploading lots of photos with the manual uploader. For example:

    python time_split.py path cutoff_time

If no cutoff time is given, it will be estimated based on the between-photo differences.


**add_project.py**

Writes the project tokens to the EXIF of images in the given path. This way, you can add photos to a project programmatically. Use like this:

    python add_project.py path 'project name'


**download_images.py**

Script to download images using the Mapillary image search API. Downloads images inside a rect (min_lat, max_lat, min_lon, max_lon).

    download_images.py min_lat max_lat min_lon max_lon max_results(optional)

