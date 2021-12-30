# Changelog

All notable changes to this project will be documented in this file. See [standard-version](https://github.com/conventional-changelog/standard-version) for commit guidelines.

## [0.8.1](https://github.com/mapillary/mapillary_tools/compare/v0.8.0...v0.8.1) (2021-12-30)


### Features
* Add Upload API to README.md
* Add upload history #464
* Add direct upload support for BlackVue videos #462
* Improve error handling (exit codes) and logging messages (#484)
* Feature: support uploading multiple files/directories at once (#486)

### Bug Fixes

* Use image exif time for interpolation by default but provide options to sepcify gpx start time #445
* Fix gpxpy's incompatible timezone-aware datetime #446
* Login API returns error messages in en_US
* Ensure zipping is deterministic
* Default camera angle to 0 before applying offset_angle
* Extract model/device from EXIF when geotag from gpx #469
* Show tqdm when log level is lower than DEBUG (#479)
* Process only specified video sample images in video_process (#480)
* EXIF read related fixes (#490)
  * Write MAPAltitude in image description
  * Return None instead of 0, if the rational denominator is 0 when reading float values, e.g. GPS, directions, etc.
  * A workaround that fixes GoPro HERO 9 subseconds reading
* Delete invalid tags before writing exif ([#489](https://github.com/mapillary/mapillary_tools/issues/489)) ([b6a18ea](https://github.com/mapillary/mapillary_tools/commit/b6a18ea6135584d220e8f4a68471cc3244428daa))

### Breaking changes

* Rename environment variables
  * rename `MAPILLARY_WEB_CLIENT_ID` to `MAPILLARY_CLIENT_TOKEN`
  * rename `GLOBAL_CONFIG_FILEPATH` to `MAPILLARY_CONFIG_PATH`
* Remove --organization_username

### Improvement
* Hide banner in ffmpeg and ffprobe (#474)

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
* Added download of blurred images uploaded by the authenticated user 
* Allow GPX files without altitude data
* More robust support of irregular time formats in EXIF
* Add argument to skip subfolders to all commands
* More robust support for filenames including irregular characters on different platforms
* Improve error information display

### Bug fixes

* Fixed bug where orientation was ignored if it was 0

## 0.5.3 (2020-07-30)

Fixes:
- fixed 404 errors on upload session closing

## 0.6.0 (2021-02-26)

Major changes:
- Upgrade to Python3 and drop the support for Python 2 #377

Fixes:
- Fix the `--save_local_mapping` support #334
- Fix the `stream_id` in gpx_from_gopro.py #356

Breaking changes:
- Remove option `--api_version`
- Remove the standalone script `bin/download_images.py`

## 0.7.0 (2021-06-11)

Major changes:
- Upgrade upload APIs to the new platform #393

Fixes:
- Fix process_csv #400
- Fix video_process for blackvue videos #397
- Fix sub_sec field https://github.com/mapillary/mapillary_tools/issues/388

Improvement:
- Remove PIL as a dependency #401
- Improve login error handling #404

Breaking changes:
- Remove subcommand `send_videos_for_processing` because it is not supported in the new system yet #393
- Remove subcommand `download` and `download_blurred` for the same reason #393
- Remove master key (was used for employee) #393

## 0.7.1 (2021-06-22)

Major changes:
- Support resumable upload #414
- Add back the progress bar for uploading #414

Fixes:
- Fix processing JPEG that has invalid thumbnail data in EXIF #415
- Fix Mapillary Tools version in EXIF #409
- Fix None columns when processing CSV #406

Improvement:
- Improve the reliability for large file uploading #414 #408

Breaking changes:
- Remove API v3 support #411

## 0.7.2 (2021-06-28)

Major changes:
- Support upload for organization #418


## 0.7.3 (2021-07-15)

Fixes:
- GoPro video processing #423 #426

Improvement:
- Recommend users download binaries in QuickStart #425
- Retries on all upload API calls, and retries more frequently #427
- Error message improvement #422 and the commit ea6f0cdf


## 0.7.4 (2021-07-28)

Fixes:
- Fix organization description missing from the API #429
- Skip BlackVue videos that have no GPS data found #430

## 0.8.0 (2021-10-07)

## Features
- Immutable process and upload: do not modify images 0430c711f06678380ccd15f6b539c16d02eeb721 #276
- The command `process` writes all metadata a single file (image description file) instead of multiple files 081e6f6daaa5827fc148d2f48062b56ab8ca732b #269
- The command `upload` supports upload given a image folder and a image description file (for advanced usages)

## Improvement
- Simplify internal image states (now an image has only 3 states processed, not_processed, failed) a859732b69b76d3b9ba9c96bfc4287c9e738687c
- Simplify command line UI (which introduces some breaking changes)
- Improve the processing performance -- less image EXIF reading/writing #251
- Improve sequence processing a859732b69b76d3b9ba9c96bfc4287c9e738687c #383 #395
- More unit tests and integration tests 5263409dc6d12ef89e89f09e13cceaf7c52df244 f1d488b708a06e915a0cba48d110c7b36db28ec8
- Use the logging module to log messages/events 5263409dc6d12ef89e89f09e13cceaf7c52df244 #342
- Update/Improve README.md a728461bc4c6a1090633bc0ffcab5e9286dde793
- Upgrade `piexif==1.1.3` and ` exifread==2.3.2` to latest a728461bc4c6a1090633bc0ffcab5e9286dde793 #398

## Breaking changes
### UI changes
- Remove `--import_path`: Instead of `process --import_path path/to/images`, use `process path/to/images`
- Remove `--advanced`: Not needed
- Remove `--rerun`: always rerun (re-process) due to performance improvement and less states c3886884166df22a6a806ddb01b9f4ae9164412b

### Other changes
- Remove command `post_process`: No need because all information are written in the description file 60ee64749a97ec71b65c7f832f2f69ba967812da
- Remove command `interpolate`
- Remove command `process_csv`: Will add back as a geotag source
- Remove all `extract_*` commands: No need because all information are written in the description file

## Other fixes:
- Fix missing GPS reference 60ee64749a97ec71b65c7f832f2f69ba967812da
- https://github.com/mapillary/mapillary_tools/issues/433
- https://github.com/mapillary/mapillary_tools/issues/437
- https://github.com/mapillary/mapillary_tools/issues/338
