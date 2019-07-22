## 0.0.0 (2018-05-30)


### Breaking changes

* The library has been rewritten for this initial release. The library usage is different from before. Refer to the documentation in the [README](https://github.com/mapillary/mapillary_tools/blob/mapillary_tools_v2/README.md) for instructions on requirement installation and usage. Due to an incompatible logging procedure, previous tools need to be used to finish uploading any sequences that were partially uploaded with the previous tools.

### Features and improvements
* Improved authentication procedure
* Improved user interface with only one executable that can run several basic tools with basic arguments, as well as advanced tools and/or advanced arguments
* Improved logging procedure
* Simpler installation with pip
* Modules can be imported in Python to enable easier development of custom process and/or upload scripts

### Bug fixes
* Inadequate README [#219](https://github.com/mapillary/mapillary_tools/issues/219), [#180](https://github.com/mapillary/mapillary_tools/issues/180), [#159](https://github.com/mapillary/mapillary_tools/issues/159), [#229](https://github.com/mapillary/mapillary_tools/issues/229), [#226](https://github.com/mapillary/mapillary_tools/issues/226), [#157](https://github.com/mapillary/mapillary_tools/issues/157)
* Removal of obsolete scripts [#162](https://github.com/mapillary/mapillary_tools/issues/162)
* Inadequate logging [#63](https://github.com/mapillary/mapillary_tools/issues/63)


## 0.0.1 (2018-06-04)

### Bug fixes
* Store the subsecond estimations done in sequence processing in case of identical timestamps


## 0.0.2 (2018-06-20)

### Bug fixes
* Update the timestamps list in case duplicates are flagged


## 0.1.0 (2018-06-12)

### Breaking changes

* Logging was modified to store log files in a hidden directory where the image is located and not in the import path.

### Features and improvements
* DONE file is created in the import path and not where the tools are being run from.
* exifread version requirement upgraded to resolve installation issues
* support geotagging from a csv file
* support various interpolations
* support re-authentication as a command
* support option to keep the original images intact
* print out version
* increase the amount of information printed out without the verbose flag.


## 0.1.4 (2018-08-14)

### Bug fixes
* Create .mapillary folder for image copies in case of passing `--keep_original`
* Add missing global variable EPOCH in interpolation

### Features and improvements
* Do not require filename column to be passed when processing csv, but align csv data and images in order by image file names if filename column is missing
* Support partial matching between image file names and file names in the csv file

## 0.1.5 (2018-08-23)

### Bug fixes
* Do not delete the import path in case it is specified as an import path for video files to be sampled into and that particular video file was already sampled into that import path, but rather issue a warning that user needs to delete existing frames that were sampled in any previous runs

## 0.1.6 (2018-08-29)

### Features and improvements
* Sample video frames into a made up sub directory `.mapillary/sampled_video_frames/"video filename"`, either where the video is located or in the import path if it is specified.
* Add command line arguments for `user_name`, `user_email` and `user_password` for `authenticate` command, in order to avoid the prompt.

## 0.1.7 (2018-09-18)

### Bug fixes
* Fix bug that resulted in sub seconds added twice in case subseconds were written to capture time tag as well as sub second time tag.

## 0.2.0 (2018-09-23)

### Features and improvements
* Additional information and progress bars under verbose in process,
* Partial optimization in DONE file sending,
* Post process command covering process summary, list of image status and options to move image according to status
* Extend support in csv processing
* Adding number of threads and max attempts in upload as command line arguments

### Bug fixes
* Correct the last interpolated direction

## 0.3.0 (2018-10-31)

### Features and improvements
* Enable specification of a time offset in case of already geotagged images
* Add better progress bars and information output in process
* Support Blackvue videos with embedded gps data
* Add a simple `download` command to download all the blurred imaged from Mapillary for a certain `import_path`
* Support import of multiple videos

### Breaking changes
* Argument `--video_file` was renamed to `--video_import_path` as directories of one or more videos can now be processed and uploaded. Note that even if one video is to be processed and uploaded, the directory of the video should be specified as the video import path and not the video file itself.
* Only the Image Description EXIF tag is overwritten with the mapillary image description which includes all the data obtained during the `process` command. If one would like the rest of the tags to be overwritten, an additional argument needs to be passed under advanced usage. Single specific tags can also be overwritten by additional specific corresponding arguments.

## 0.3.1 (2018-12-10)

### Features and improvements
* mapillary_tools available to be downloaded and installed as a package

## 0.4.0 (2019-01-10)

### Features and improvements
* Improved upload stability
* Improved processing of Blackvue videos with embedded gps data
* Added features for process_csv command
* More options for storing local image file path
* Improved and added features for post_process command

### Breaking changes
* Argument `--video_import_path` can be single video or a directory of videos  
* Duplicate flagging is now done automatically with the default duplicate thresholds. To keep duplicates, argument `--keep_duplicates` must be passed.

### Bug fixes
* Store username in case authenticating manually

## 0.4.1 (2018-01-22)

### Features and improvements
 * Fix ipc exif encoding to support desktop uploader

## 0.4.2 (2018-01-25)

### Features and improvements
 * Enable JWT authentication to support desktop uploader

## 0.5.0 (2019-03-28)

### Features and improvements
* Added command to upload Blackvue DR900S videos directly to Mapillary
* Added download of images selected by image key
* Allow GPX files without altitude data
* More robust support of irregular time formats in EXIF
* Add argument to skip subfolders to all commands
* More robust support for filenames including irregular characters on different platforms
* Improve error information display

### Bug fixes

* Fixed bug where orientation was ignored if it was 0