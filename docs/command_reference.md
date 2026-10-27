<!--
Copyright (c) Meta Platforms, Inc. and affiliates.

This source code is licensed under the BSD license found in the
LICENSE file in the root directory of this source tree.
-->

# Command reference

What each mapillary_tools command does, how to use it, and what to watch out for.
For the full list of options of the version you have installed, run `mapillary_tools COMMAND --help`.

- [Overview](#overview)
- [Common concepts](#common-concepts)
  - [Import paths](#import-paths)
  - [The description file](#the-description-file)
  - [Sequences and checks](#sequences-and-checks)
- [process_and_upload](#process_and_upload)
- [process](#process)
- [Geotag sources](#geotag-sources)
  - [--geotag_source](#--geotag_source)
  - [--video_geotag_source](#--video_geotag_source)
  - [GPX and NMEA tracks](#gpx-and-nmea-tracks)
  - [ExifTool](#exiftool)
- [upload](#upload)
- [sample_video](#sample_video)
- [video_process](#video_process)
- [video_process_and_upload](#video_process_and_upload)
- [authenticate](#authenticate)
- [check_upload_history](#check_upload_history)
- [zip](#zip)
- [Exit codes](#exit-codes)
- [Environment variables](#environment-variables)

## Overview

| Command                    | What it does                                                                                       |
| -------------------------- | -------------------------------------------------------------------------------------------------- |
| `process_and_upload`       | `process`, then `upload`. The command most users need.                                             |
| `process`                  | Reads the time and GPS position of images and videos, checks them, and writes the description file. |
| `upload`                   | Uploads the images and videos that `process` described.                                            |
| `sample_video`             | Extracts frames from videos as geotagged images. Needs FFmpeg.                                     |
| `video_process`            | `sample_video`, then `process` the frames.                                                         |
| `video_process_and_upload` | `video_process`, then `upload` the frames.                                                         |
| `authenticate`             | Adds, updates or deletes user profiles, and deletes saved organization names.                      |
| `check_upload_history`     | Tells whether processed files were already uploaded from this computer.                            |
| `zip`                      | Writes processed image sequences into zip files, to upload later.                                  |

Two options go before the command name: `--version`, and `--verbose` for debug logs, as in
`mapillary_tools --verbose process MY_CAPTURE_DIR`. After the command name, `--verbose` is rejected.

## Common concepts

### Import paths

The commands take one or more files or directories.

- Directories are searched recursively. `--skip_subfolders` reads only the top level. Hidden files and folders
  (names starting with `.`) are skipped.
- In a directory, files that are not supported images or videos are left out without a word.
- A file named on the command line that is not a supported image or video fails with
  `MapillaryUnsupportedFileError`. For an Insta360 `.insv` original, the error explains how to stitch it first.
  Sidecar and companion files (`.gpx`, `.nmea`, `.xml`, `.json`, `.thm`, `.lrv`, `.srt`, `.txt`, `.DS_Store` and
  the like) are skipped with a warning instead, so that `process DCIM/100GOPRO/*` works. Zip files are
  uploaded as they are.
- Images are JPEG files with a capture time and a GPS position (or a GPS track to place them on). Videos need GPS
  of their own, or a GPX or NMEA track, or GPS that ExifTool can read. See [Geotag sources](#geotag-sources).

### The description file

`process` writes a JSON array with one entry per file: its capture time, position, direction and device, or an
`error` entry that says why it failed. `upload` reads it. The format is defined by the
[image description schema](../schema/image_description_schema.json); you can edit or generate the file yourself.

- Where `process` writes it: `IMPORT_PATH/mapillary_image_description.json` when the only import path is a
  directory. With several import paths, or a single file, it goes to STDOUT, with a warning. `--desc_path PATH`
  sets the path, and `-` means STDOUT.
- `upload` reads it from the same default place, and needs `--desc_path` otherwise (`-` reads STDIN).
- File names in it are absolute. `upload` uploads the entries without an error whose files are under the import
  paths it is given, so do not move the files between `process` and `upload`.
- `process` writes it before it fails, so a later `upload` uploads the files that did not fail.
- `upload` checks every entry against the schema, and stops at one that does not match (exit code 15).

### Sequences and checks

`process` groups images into sequences: by folder, camera (make, model and serial number) and image size, sorted
by capture time. Images in different folders never share a sequence. A sequence is split where:

- the time between two images exceeds `--cutoff_time` (60 s),
- the distance between two images exceeds `--cutoff_distance` (100 m),
- it reaches 1000 images, 110 GB or 6 gigapixels.

Then each file is checked. Files that fail a check get an error entry and are not uploaded:

| Check                                   | Applies to      | Error                                                                    |
| --------------------------------------- | --------------- | ------------------------------------------------------------------------ |
| Same position and direction as the image before it (`--duplicate_distance` 0.1 m, `--duplicate_angle` 5°) | images | `MapillaryDuplicationError`, which does not fail the command |
| Position (0, 0)                         | images, videos  | `MapillaryNullIslandError`                                               |
| Average speed above 400 km/h            | sequences, videos | `MapillaryCaptureSpeedTooFastError`                                    |
| GPS positions that jump back and forth  | sequences       | `MapillaryZigZagError` (turn off with `--skip_zigzag_check`)             |
| All GPS points within 10 m              | videos          | `MapillaryStationaryVideoError`                                          |
| No GPS points                           | videos          | `MapillaryVideoGPSNotFoundError`                                         |
| GPS points too far apart in time for the uploaded video to store | videos | `MapillaryGPSPointsTooFarApartError`; a GPS timestamp is probably wrong |
| Larger than 110 GB                      | videos          | `MapillaryFileTooLargeError`                                             |

## process_and_upload

```sh
mapillary_tools process_and_upload IMPORT_PATH [IMPORT_PATH ...] [OPTIONS]
```

Runs [`process`](#process) and then [`upload`](#upload), and takes the options of both.

```sh
mapillary_tools process_and_upload MY_CAPTURE_DIR MY_VIDEO_DIR/*.mp4 \
    --user_name my_profile \
    --organization_name work
```

Gotchas:

- It logs in first, before processing (see [`upload`](#upload) for profiles and prompts).
- If any file fails to process, nothing is uploaded and the command exits with code 6. With
  `--skip_process_errors`, the files that did not fail are uploaded.
- It writes no description file, unless you give `--desc_path`.
- Zip files in the import paths (from the [`zip`](#zip) command) are uploaded as they are.

## process

```sh
mapillary_tools process IMPORT_PATH [IMPORT_PATH ...] [OPTIONS]
```

Reads the capture time and GPS position of each image and video from the [geotag sources](#geotag-sources),
groups the images into sequences, runs the [checks](#sequences-and-checks), and writes the
[description file](#the-description-file). It uploads nothing, and it does not change your files unless you
give an `--overwrite_*` option.

| Option                                 | Default                       | Description                                                                                         |
| -------------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------------- |
| `--skip_subfolders`                    |                               | Read only the top level of each directory.                                                          |
| `--filetypes TYPES`                    | all                           | Comma-separated: `image`, `video`, or one type of video (`gopro`, `camm`, `blackvue`). Also `--file_types`. |
| `--skip_process_errors`                |                               | Exit 0 when some files fail. They still get an error entry and are not uploaded.                    |
| `--desc_path PATH`                     | see above                     | Where to write the description file. `-` for STDOUT.                                                |
| `--process_report_path PATH`           |                               | Write a JSON report of the files found and the unsupported files skipped.                           |
| `--geotag_source SOURCE`               | `native`, `exiftool_runtime`  | Where to read times and positions from. Repeatable. See [Geotag sources](#geotag-sources).          |
| `--geotag_source_path PATH`            |                               | The track or XML file for the sources that read one.                                                |
| `--video_geotag_source SOURCE`         |                               | Geotag sources for videos only. Repeatable.                                                         |
| `--interpolation_offset_time SECONDS`  | 0                             | Seconds added to capture times to find positions on a GPX, NMEA or video track.                     |
| `--interpolation_use_gpx_start_time`   |                               | Place the first image, or the start of a video, at the first point of the track.                    |
| `--offset_time SECONDS`                | 0                             | Seconds added to image capture times after geotagging. Does not move images.                        |
| `--offset_angle DEGREES`               | 0                             | Degrees added to image directions.                                                                  |
| `--interpolate_directions`             |                               | Point each image at the next one, instead of using the direction from EXIF.                         |
| `--cutoff_time`, `--cutoff_distance`   | 60 s, 100 m                   | Where to split sequences.                                                                           |
| `--duplicate_distance`, `--duplicate_angle` | 0.1 m, 5°                | When an image counts as a duplicate of the one before it. `--duplicate_angle 360` ignores direction. |
| `--skip_zigzag_check`                  |                               | Do not fail sequences whose GPS zig-zags.                                                           |
| `--device_make`, `--device_model`      |                               | Override the camera make and model.                                                                 |
| `--overwrite_all_EXIF_tags`            |                               | Write the processed time, position, direction and orientation into the EXIF of the images. `--overwrite_EXIF_time_tag`, `--overwrite_EXIF_gps_tag`, `--overwrite_EXIF_direction_tag` and `--overwrite_EXIF_orientation_tag` write one each. |
| `--num_processes N`                    | number of CPUs                | Worker processes. 0 or less turns multiprocessing off.                                              |

```sh
# Images and videos with their own GPS
mapillary_tools process MY_CAPTURE_DIR

# Images geotagged from a GPX track, with the camera clock 8 hours ahead of the GPS
mapillary_tools process MY_IMAGE_DIR \
    --geotag_source gpx --geotag_source_path track.gpx \
    --interpolation_offset_time -28800

# Write a report of what was found and skipped
mapillary_tools process MY_CAPTURE_DIR --process_report_path report.json
```

The process report (version 1) has `discovered_file_count`, `processed_file_count` (which counts the files that
failed to process too), `skipped_file_count`, and `skipped_files` with the name, category, reason code and
extension of each unsupported file. An unsupported file named on the command line is always reported. The report
holds absolute file names, so treat it as private.

Gotchas:

- The command exits with code 6 if any file fails, after writing the description file.
- A directory with both images and videos processes both. Use `--filetypes image` or `--filetypes video` to
  pick one.
- Processing a video folder after [`video_process`](#video_process) also finds the frames it wrote into
  `mapillary_sampled_video_frames`, so `process_and_upload` would upload both the videos and their frames. Pass
  the videos themselves, or move the frames away.
- `--offset_time` shifts the capture times after geotagging, and leaves positions alone.
  `--interpolation_offset_time` shifts them before they are placed on a track, so it moves the images too. Both
  change the capture time that is uploaded: to fix a camera clock against a GPX, use
  `--interpolation_offset_time` alone.
- The `--overwrite_*` options modify your original images.
- Images whose only date is a placeholder, or before 1970, fail. So do EXIF GPS minutes or seconds above 60.

## Geotag sources

### --geotag_source

Sources are tried in order. A file that a source finds no GPS for, or places outside its track, goes to the
next source, and if none geotags it, it gets the error of the last one that tried. Other errors end the search:
a track file that is not valid, or has no time that can be read, fails the files it was to geotag, even if a
later source could have. A video whose own GPS is rejected as empty or noisy goes on only to `gpx` and `nmea` sources.
Repeat the option or separate sources with commas. The default is `native`, then `exiftool_runtime`.

| Source                          | Images                                                     | Videos                                                                         |
| ------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `native`                        | EXIF                                                       | The GPS of the video: GoPro (GPMF), CAMM, BlackVue, and Novatek-based dashcams |
| `exif`                          | EXIF                                                       | Cannot read videos                                                             |
| `exiftool_runtime` (`exiftool`) | Runs ExifTool on the image                                 | Runs ExifTool on the video                                                     |
| `exiftool_xml`                  | Reads the output of `exiftool -X`, by default `%g.xml` beside the file | The same                                                           |
| `gpx`                           | Places images on the GPX track by capture time (needs `--geotag_source_path`) | Places the video on the GPX track (by default `%g.gpx` beside it) |
| `nmea`                          | The same, from an NMEA log                                 | The same, by default `%g.nmea`                                                 |
| `gopro`, `camm`, `blackvue`     | Places frames that `sample_video` took from a video on the GPS track of that video, whatever its type (needs `--geotag_source_path` to the video or its folder) | Cannot read videos |

`--geotag_source_path PATH` gives the file to every source that reads one. A source can also be given as a JSON
object, to set its own options:

```sh
mapillary_tools process MY_CAPTURE_DIR \
    --geotag_source '{"source": "gpx", "source_path": "track.gpx", "filetypes": ["image"]}' \
    --geotag_source native
```

The keys are `source`, `filetypes`, `source_path`, `pattern` (see below), `interpolation_offset_time` and
`interpolation_use_gpx_start_time`.

Gotchas:

- A file that no source is given for fails. For example, `--geotag_source exif` on a folder with videos fails the
  videos, and a source limited with `"filetypes": ["image"]` leaves the videos without one.
- `gpx` and `nmea` for images need a single track file, given with `--geotag_source_path`. Without it, the
  command stops (exit code 2) if it finds any image.

### --video_geotag_source

Geotag sources for videos only. They are tried before the `--geotag_source` sources, which then geotag the images
and the videos left. If `--geotag_source` is not given, images (including the frames that `video_process` samples)
are still geotagged by the default sources.

| Source                                | Reads                                                         | Default pattern |
| ------------------------------------- | ------------------------------------------------------------- | --------------- |
| `native` (`video`)                    | The GPS of the video, in any format that `native` reads       | none            |
| `gopro`, `camm`, `blackvue`           | The GPS of the video, only in videos of that type             | none            |
| `gpx`                                 | A GPX file                                                    | `%g.gpx`        |
| `nmea`                                | An NMEA log                                                   | `%g.nmea`       |
| `exiftool_xml`                        | An XML file written by `exiftool -X`                          | `%g.xml`        |
| `exiftool_runtime`                    | Runs ExifTool on the video, or on the file the pattern names  | `%f`            |

The pattern names the file to read, starting from the video file name: `%f` is the full name (`foo.mp4`), `%g`
the name without extension (`foo`), and `%e` the extension (`.mp4`). A relative pattern is relative to the folder
of the video. Whether a pattern is case-sensitive depends on the file system: `%g.gpx` finds `foo.GPX` on Windows
and, by default, on macOS, but not on Linux.

```sh
# foo.mp4 is geotagged from foo.gpx beside it
mapillary_tools process VIDEO_DIR --video_geotag_source gpx

# Stitched Insta360 videos: try a GPX first, then the GPS of the original .insv in the parent folder
mapillary_tools process VIDEO_DIR \
    --video_geotag_source gpx \
    --video_geotag_source '{"source": "exiftool_runtime", "pattern": "../%g.insv"}'
```

Gotchas:

- `gopro`, `camm` and `blackvue` fail videos of another type, and say so.
- `--geotag_source_path` overrides the patterns of `gpx` and `nmea`, also those given in JSON: every video is
  then placed on that one track.

### GPX and NMEA tracks

Images are placed on the track by their capture time; videos by the times of their frames.

- Only GPX track points (`<trkpt>`) are read: routes and waypoints are not. Points without a `<time>` are left out.
  A GPX file in which no track point has a time that can be read fails as `MapillaryInvalidGPXError`, which
  says why, as does a file that is not valid GPX. If only some times cannot be read, those points are left
  out with a warning.
- NMEA logs need GGA sentences, for the position and time of each fix, and RMC sentences, for the date.
  Malformed sentences are skipped with a warning.
- Files outside the track fail with `MapillaryOutsideGPXTrackError`: images captured before the track starts,
  after it ends, or in a gap of more than an hour between two points (such as between two trips in one file).
  Set `MAPILLARY_TOOLS_MAX_GPX_GAP_SECONDS` to allow longer gaps.
- If the camera and GPS clocks differ, `--interpolation_offset_time N` adds N seconds to the capture times before
  placing them. It moves videos geotagged from a track too: in a folder with images and videos, an offset that
  fixes the image camera clock can push the videos off their tracks. Process the images alone with
  `--filetypes image`.
- `--interpolation_use_gpx_start_time` places the first image, or the start of each video, at the first point of
  the track (then the offset applies). Like the offset, it shifts the capture times of the images.

How a track is lined up with a video:

- A video with GPS of its own is synced to the track by its GPS clock, and in `process` the track is cut to the
  video.
- In `process`, a video without GPS is assumed to start with the track. If the track lasts more than twice as
  long as the video, it warns: unless the video is a timelapse of the whole track, trim the track to the video,
  or sample the video with `video_process` and `--video_start_time`.
- In `video_process`, give the start time of a video without GPS with `--video_start_time`, in UTC. Without it,
  distance sampling assumes that the track starts with the video, and refuses a track more than twice as long
  as the video (the error prints the start of the track, to pass as `--video_start_time`). Interval sampling
  reads the start time from the creation time of the video instead.
- In `video_process`, give a timelapse without GPS of its own `--video_duration_ratio`: the seconds of capture
  per second of video, such as 60 for one frame every 2 seconds played at 30 frames per second.

### ExifTool

[ExifTool](https://exiftool.org/) reads GPS from many cameras that `native` does not. It is optional: install it
and put it on the `PATH`, or set `MAPILLARY_TOOLS_EXIFTOOL_PATH`.

Gotchas:

- Without ExifTool, files that `native` cannot read fail with `MapillaryExiftoolNotFoundError`, which may hide
  that they have no GPS at all.
- GPS points that ExifTool reads with a time more than an hour (`MAPILLARY_TOOLS_MAX_GPX_GAP_SECONDS`) from the
  rest of the track, such as a stale first fix of a dashcam, are left out with a warning.

## upload

```sh
mapillary_tools upload IMPORT_PATH [IMPORT_PATH ...] [--desc_path PATH] [OPTIONS]
```

Uploads the images (as sequences), videos and zip files under the import paths, using the
[description file](#the-description-file) that `process` wrote.

| Option                       | Default       | Description                                                                                       |
| ---------------------------- | ------------- | ------------------------------------------------------------------------------------------------- |
| `--desc_path PATH`           | see above     | The description file. `-` for STDIN.                                                              |
| `--user_name PROFILE`        |               | The profile to upload with (see [`authenticate`](#authenticate)).                                 |
| `--organization_key ID`      |               | Upload to the organization with this ID.                                                          |
| `--organization_name NAME`   |               | Upload to the organization saved under NAME in the profile. With `--organization_key ID`, save the ID under NAME. |
| `--num_upload_workers N`     | 4             | Concurrent image uploads.                                                                         |
| `--reupload`                 |               | Upload again what was uploaded before.                                                            |
| `--dry_run`                  |               | Write the uploads to a local folder instead of Mapillary (for testing).                           |
| `--noresume`                 |               | Start interrupted uploads from the beginning.                                                     |
| `--nofinish`                 |               | Upload without finishing: nothing appears on Mapillary (for testing).                             |

```sh
mapillary_tools process MY_CAPTURE_DIR
mapillary_tools upload MY_CAPTURE_DIR --user_name my_profile

# Save the organization ID under the name "work" once, then use the name
mapillary_tools upload MY_CAPTURE_DIR --organization_key 1234567890 --organization_name work
mapillary_tools upload MY_CAPTURE_DIR --organization_name work
```

Gotchas:

- With no profile yet, it asks you to log in. With several profiles, it asks which one, unless you give
  `--user_name`. When it cannot prompt (no terminal, or `MAPILLARY_TOOLS_PROMPT_DISABLED=YES`), it fails instead.
- Image sequences, videos and zip files already uploaded from this computer are skipped. Each is compared as a
  whole, by a checksum: a sequence with one image added or removed counts as new and is uploaded again, and a
  video is recognized by its file alone, even if its track changed. The upload history is kept on this computer
  only. `--dry_run` neither reads nor writes it.
- An interrupted upload resumes where it stopped the next time you upload the same files.
- `--organization_key` takes a numeric ID. Organization names are 2 to 32 letters, digits, `-` and `_`, starting
  with a letter, and are case-sensitive. Saving a name again with another ID replaces it.
- A file that fails to upload does not stop the others, and the command still exits with code 0: check the
  upload summary. Connection errors, time-outs, authorization errors and other HTTP errors stop the command
  (exit codes 12, 13, 14 and 16).
- Uploading a folder of zip files also needs a description file: pass the one of the zipped images with
  `--desc_path`.

## sample_video

```sh
mapillary_tools sample_video VIDEO_IMPORT_PATH [IMPORT_PATH] [OPTIONS]
```

Extracts frames from each video, with FFmpeg, as JPEG images with their capture time and, when known, their
position in EXIF.
By default it takes one frame every 3 m along the GPS track of the video (distance sampling). The frames of
`VIDEO_DIR/sub/foo.mp4` go into `IMPORT_PATH/sub/foo.mp4/`. `IMPORT_PATH` defaults to
`VIDEO_IMPORT_PATH/mapillary_sampled_video_frames` (beside the video, for a single video).

| Option                              | Default | Description                                                                                       |
| ----------------------------------- | ------- | ------------------------------------------------------------------------------------------------- |
| `--video_sample_distance METERS`    | 3       | Distance between frames. `-1` turns distance sampling off.                                        |
| `--video_sample_interval SECONDS`   |         | Time between frames, with `--video_sample_distance -1`.                                           |
| `--video_start_time TIME`           |         | Start time of the videos, in UTC, as `YYYY_MM_DD_HH_MM_SS_sss`. Places a video without GPS on a GPX track. |
| `--video_duration_ratio RATIO`      | 1       | Seconds of capture per second of video, for a timelapse without a GPS clock.                      |
| `--skip_subfolders`                 |         | Read only the top level of `VIDEO_IMPORT_PATH`.                                                   |
| `--rerun`                           |         | Delete the frames of earlier runs and sample again.                                               |
| `--skip_sample_errors`              |         | Exit 0 when some videos fail to sample.                                                           |

Gotchas:

- FFmpeg (`ffmpeg` and `ffprobe`) must be installed, or set `MAPILLARY_TOOLS_FFMPEG_PATH` and
  `MAPILLARY_TOOLS_FFPROBE_PATH`.
- `sample_video` reads the GPS of the videos with the built-in readers only: not with ExifTool, nor from a GPX
  or NMEA track. For those, use [`video_process`](#video_process) with a geotag source.
- A video that was sampled before is skipped, even if the options changed. Give `--rerun` to sample it again.
- Distance sampling needs a GPS track: a video without one fails. Videos that fail do not stop the others; the
  command fails at the end, unless `--skip_sample_errors` is given.
- `--video_start_time` applies to every video in the command. To place several videos on one GPX track, run the
  command once for each video.

## video_process

```sh
mapillary_tools video_process VIDEO_IMPORT_PATH [IMPORT_PATH] [OPTIONS]
```

Runs [`sample_video`](#sample_video), then [`process`](#process) on the frames, and takes the options of both.
The description file goes into `IMPORT_PATH` by default.

```sh
# One frame every 5 m
mapillary_tools video_process VIDEO_DIR MY_FRAMES --video_sample_distance 5

# A video without GPS, along a GPX track, starting at a known time
mapillary_tools video_process MY_VIDEO.mp4 \
    --geotag_source gpx --geotag_source_path track.gpx \
    --video_start_time 2025_03_14_07_00_30_000
```

Gotchas:

- It processes the frames only, never the videos. It prints a warning that it sets `--filetypes image`.
- If some videos fail to sample, it still processes the frames of the others, then fails (exit code 7, or 6
  if frames failed to process as well).
  `--skip_sample_errors` skips those videos. Errors in processing the frames are skipped with
  `--skip_process_errors`.
- Unlike `process`, it does not look for a track beside each video by the default pattern: without
  `--geotag_source_path`, give the pattern, as in
  `--video_geotag_source '{"source": "gpx", "pattern": "%g.gpx"}'`.

## video_process_and_upload

```sh
mapillary_tools video_process_and_upload VIDEO_IMPORT_PATH [IMPORT_PATH] [OPTIONS]
```

Runs [`video_process`](#video_process), then uploads the frames. It takes the options of both.

Gotchas:

- If any video fails to sample, nothing is uploaded, unless `--skip_sample_errors` is given.
- As with `process_and_upload`, it logs in first and writes no description file unless `--desc_path` is given.

## authenticate

```sh
mapillary_tools authenticate [--user_name PROFILE] [OPTIONS]
```

Logs in to Mapillary and saves the credentials as a profile in the config file
(`~/.config/mapillary/configs/`, or `MAPILLARY_CONFIG_PATH`). It lists the existing profiles first, with the
organization names saved in each.

| Option                       | Description                                                                         |
| ---------------------------- | ----------------------------------------------------------------------------------- |
| `--user_name PROFILE`        | The profile name: a local name of your choice, not necessarily your Mapillary user name. |
| `--user_email`, `--user_password` | Log in without prompts.                                                         |
| `--jwt TOKEN`                | Save a user access token instead of logging in.                                     |
| `--delete`                   | Delete the profile, or with `--organization_name NAME`, only that saved name.       |

```sh
mapillary_tools authenticate --user_name my_profile
mapillary_tools authenticate --user_name my_profile --delete
mapillary_tools authenticate --user_name my_profile --organization_name work --delete
```

Gotchas:

- Authenticating an existing profile again replaces its credentials, and keeps its saved organization names.
- Organization names are saved by `upload`, not by `authenticate`
  (`--organization_key ID --organization_name NAME`).
- Without a terminal, or with `MAPILLARY_TOOLS_PROMPT_DISABLED=YES`, give everything as options: missing values
  are an error instead of a prompt.

## check_upload_history

```sh
mapillary_tools check_upload_history IMPORT_PATH [IMPORT_PATH ...] [--desc_path PATH]
```

Tells whether the processed image sequences, videos and zip files were uploaded from this computer before. Takes
the same import paths and description file as `upload`, and prints a JSON array with one entry per sequence,
video or zip file: its file type, sequence UUID, checksum, file names, `already_uploaded_filenames`, and
`already_uploaded`, which is true only when all its files are in the history. Images are looked up one by one,
also in sequences uploaded before, so it can report as uploaded a sequence that `upload` would upload again.

It reads only the local upload history: it needs no login, makes no network requests, and changes nothing.
Uploads from another computer, or with `--dry_run`, are not in it.

## zip

```sh
mapillary_tools zip IMPORT_PATH ZIP_DIR [--desc_path PATH]
```

Writes each processed image sequence under `IMPORT_PATH` into a zip file in `ZIP_DIR`, with the metadata in the
images. `upload` uploads zip files as they are, so they can be uploaded later. Reads the description file like
`upload`.

```sh
mapillary_tools process MY_IMAGE_DIR
mapillary_tools zip MY_IMAGE_DIR MY_ZIPS
mapillary_tools upload MY_ZIPS --desc_path MY_IMAGE_DIR/mapillary_image_description.json
```

## Exit codes

| Code | Meaning                                                                       |
| ---- | ----------------------------------------------------------------------------- |
| 0    | Success, including when errors were skipped with `--skip_*_errors`. `upload` also exits 0 when some files failed to upload |
| 1    | Unexpected error                                                              |
| 2    | Invalid option or option value                                                |
| 3    | Import path or description file not found                                     |
| 4    | The description file is not valid JSON                                        |
| 6    | Some files failed to process                                                  |
| 7    | Some videos failed to sample                                                  |
| 8    | FFmpeg not found                                                              |
| 12   | Connection error during upload                                                |
| 13   | Upload timed out                                                              |
| 14   | Not authorized: log in again with `authenticate`                              |
| 15   | An entry of the description file does not match the schema                    |
| 16   | HTTP error from the Mapillary API                                             |
| 17   | Unexpected response from the Mapillary API                                    |
| 130  | Interrupted                                                                   |

## Environment variables

| Variable                                   | Default                       | Description                                                  |
| ------------------------------------------ | ----------------------------- | ------------------------------------------------------------ |
| `MAPILLARY_CONFIG_PATH`                    | `~/.config/mapillary/configs/…` | The config file with the profiles.                         |
| `MAPILLARY_TOOLS_PROMPT_DISABLED`          | `NO`                          | `YES` to never prompt, and fail instead.                     |
| `MAPILLARY_TOOLS_EXIFTOOL_PATH`            | `exiftool`                    | The ExifTool executable.                                     |
| `MAPILLARY_TOOLS_FFMPEG_PATH`, `MAPILLARY_TOOLS_FFPROBE_PATH` | `ffmpeg`, `ffprobe` | The FFmpeg executables.                                  |
| `MAPILLARY_TOOLS_MAX_GPX_GAP_SECONDS`      | 3600                          | The longest gap in a GPX or NMEA track that files can be placed in, and how far from the rest of a track ExifTool points can be. |
| `MAPILLARY_UPLOAD_HISTORY_PATH`            | in the user data folder       | Where the upload history is kept.                            |
| `MAPILLARY_TOOLS_MAX_SEQUENCE_LENGTH`      | 1000                          | The most images in a sequence.                               |
| `MAPILLARY_TOOLS_MAX_CAPTURE_SPEED_KMH`    | 400                           | The fastest average speed that passes the speed check.       |
| `MAPILLARY_TOOLS_IMAGE_DESCRIPTION_FILENAME` | `mapillary_image_description.json` | The default name of the description file.            |
| `MAPILLARY_TOOLS_SAMPLED_VIDEO_FRAMES_FILENAME` | `mapillary_sampled_video_frames` | The default folder name for video frames.            |

The defaults of some options can also be set by environment variables, such as `MAPILLARY_TOOLS_CUTOFF_TIME`,
`MAPILLARY_TOOLS_CUTOFF_DISTANCE`, `MAPILLARY_TOOLS_DUPLICATE_DISTANCE`, `MAPILLARY_TOOLS_DUPLICATE_ANGLE` and
`MAPILLARY_TOOLS_VIDEO_SAMPLE_DISTANCE`.
