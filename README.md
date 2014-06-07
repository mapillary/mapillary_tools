mapillary_tools
===============

Useful tools and scripts related to Mapillary

upload.py
---------

This tool uploads images taken with mapillary to the mapillary server. Just call `python upload.py path-to-images/` to upload.  

On Android Systems you can find the images under ` /storage/emulated/0/Android/data/app.mapillary/files/pictures/`.

On iOS, open iTunes, select your device, and scroll down to Mapillary under apps. You can see the files and copy them over from there.


time_split.py
---------

This script organizes images into sequence groups based on a cutoff time. This is useful as a step before uploading lots of photos with the manual uploader.
