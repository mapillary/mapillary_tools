Python Tools for Mapillary
=============

## Dependencies

* [exifread]
* [gpxpy]
* [PIL]
* [Piexif]

Note that we're using a fork of [Piexif](https://github.com/hMatoba/Piexif). Please follow the instructions below to install.  

## Installing on MacOSX
    sudo pip install -r requirements.txt

If you don't have pip on your system, you can install it by `sudo easy_install pip`.

## Installing on Ubuntu

    sudo apt install git python python-virtualenv python-dev
    git clone https://github.com/mapillary/mapillary_tools.git
    cd mapillary_tools/python
    python -m virtualenv --python=python2 --system-site-packages .env
    source .env/bin/activate
    pip install -r requirements.txt
    
Run `deactivate` to exit the virtualenv.

## Importing

Use the mapillary_import.py script to process and upload images to Mapillary.
General usage:

    python mapillary_import.py tool path-to-images [arguments]

Available tools are:

- main tools:
   - process
   - upload
   - process_and_upload
- unit tools:
   - user_process
   - import_metadata_process
   - geotag_process
   - sequence_process
   - upload_params_process
   - insert_EXIF_ImageDescription
	 	
The main tools are used to complete the entire pipeline of image import.
The unit tools are tools called by the process tool, but can be run individually.
Each tool takes specific arguments.

## Processing
Required meta data needs to be processed and inserted in the image EXIF for an image to be uploaded to Mapillary.
In case the image were taken with the Mapillary app, the required meta data is already inserted in the image EXIF and no processing is needed.
Required meta data is:
- user specific meta data
-  capture time
-  latitude and longitude
-  sequence meta data
Optional meta data:
-  import meta data

**process**
By using the process tool, all of the below listed processing unit tools will be executed with the corresponding arguments.

Required arguments are:
- `path "path value"`
    path to images
    value type string
- `--user_name "user name"`
    specify the user name used to create an account at Mapillary
    value type string

Optional arguements are:
- `--verbose`
    set True to print out additional information and warnings

Other optional arguments are listed and described under each corresponding tool unit.

Simple usage example:

    python mapillary_import.py process path --user_name username_at_mapilary --verbose

More advanced usage example:

    python mapillary_import.py process path --user_name username_at_mapilary --add_file_name --add_import_date --device_make Apple --device_model "iPhone SE" --GPS_accuracy 1.5 --cutoff_distance 50 --cutoff_time 120 --interpolate_directions --offset_angle 10 --flag_duplicates --duplicate_distance 2 --duplicate_angle 45 

If a unit tool is to be skipped, argument specifying the skip for the specific unit tool has to be specified.
Usage example with skipping sequence processing:
 
    python mapillary_import.py process path --user_name username_at_mapilary --skip_sequence_processing

List of all arguments used to skip a specific unit tool:
- `--skip_user_processing`
    set True to skip processing user properties
- `--skip_import_meta_processing`
    set True to skip processing import meta data properties
- `--skip_geotagging`
    set True to skip processing geotagging properties
- `--skip_sequence_processing`
    set True to skip processing sequence properties
- `--skip_upload_params_processing`
    set True to skip processing upload parameters
- `--skip_insert_EXIF`
    set True to skip inserting the properties into image EXIF

In case of first image import for the specified user name, authentication is required.
Authentication requires the user to provide user email and password, used to create an account at Mapillary.

**user_process**
The user process tool will process user specific properties and initialize authentication in case of first import.
No additional arguments available besides the import path, user name and verbose.
Both import path and user name are required to run this process tool.
Usage example:

    python mapillary_import.py user_process path --user_name username_at_mapilary

This unit process is required for an image to be uploaded to Mapillary.
Only skip this process if you have run it already or you do not intent to upload the images to Mapillary.

**upload_params_process**
The upload_params_process tool will process user specific upload parameters, required to safely upload images to Mapillary.
This unit process requires that geotag_process and sequence_process have been run successfully.
No additional arguments available besides the import path, user name and verbose.
Both import path and user name are required to run this process tool.
Usage example:

    python mapillary_import.py upload_params_process path --user_name username_at_mapilary

This unit process is required for an image to be uploaded to Mapillary.
Only skip this process if you have run it already or you do not intent to upload the images to Mapillary.

**import_metadata_process**
The import_metadata_process tool will process import specific meta data which is not required, but can be very useful.
Additional arguments available besides the import path, user name and verbose:
- `--orientation "orientation value"`
    specify image orientation in degrees
    note this might result in image rotation
    note this input has precedence over the input read from the import source
    possible values are [0, 90, 180, 270]
- `--device_make "device make"`
    specify device manufacturer
    note this input has precedence over the input read from the import source
    value type string
- `--device_model "device model"`
		specify device model
		note this input has precedence over the input read from the import source
		value type string
- `--GPS_accuracy "GPS accuracy value"`
		specify GPS accuracy in meters
		note this input has precedence over the input read from the import source
		value type float
- `--add_file_name`
		set True to add local file name to the meta data 
- `--add_import_date`
		set True to add import date to the meta data
- `--import_meta_source "import meta source value"`
		specify the source of meta
		note values of arguments passed through the command line while calling the script take precedence over the values read from the source
		possible values are ['exif', 'json']
		default value is exif, which results in import meta data read directly from the image EXIF if available
- `--import_meta_source_path "path to file"`
		specify the path to the file with import meta
		in case import_meta_source is not set or is set to exif, this argument is not required
		value type string`

Only the import path is required to run this process tool.		
Usage examples:

    python mapillary_import.py import_metadata_process path

    python mapillary_import.py import_metadata_process path --add_file_name --add_import_date --import_meta_source exif

    python mapillary_import.py import_metadata_process path --import_meta_source json import_meta_source_path "path/to/file.json"

This unit process is not required for an image to be uploaded to Mapillary, although is very much encouraged.

**geotag_process**
The geotag_process tool will process the capture date/time and GPS data which are required to upload an image to Mapillary.
Additional arguments available besides the import path, user name and verbose:
- `--geotag_source "geotag source value"`
		specify the source of geotag data
		possible values are ['exif', 'gpx', 'csv', 'json']
		default value is exif, which results in capture date/time and GPS data read directly from the image EXIF if available
- `--geotag_source_path "path to file"`
		specify the path to the file with the capture date/time and GPS data
		in case geotag source is set to exif, this argument is not required
		value type string
- `--offset_angle	"offset angle value"`	
		specify the offset camera angle (90 for right facing, 180 for rear facing, -90 for left facing)
		value type float

Only the import path is required to run this process tool.		
Usage examples:

    python mapillary_import.py geotag_process path --user_name username_at_mapilary

    python mapillary_import.py geotag_process path --user_name username_at_mapilary --offset_angle 90 --geotag_source csv --geotag_source_path "path/to/file.csv"

This unit process is required for an image to be uploaded to Mapillary.
Only skip this process if you have run it already or you do not intent to upload the images to Mapillary.

**sequence_process**
The sequence_process tool will process the entire set of images located in the import path and flag duplicates, interpolate directions and perform sequence split.
This unit process requires that geotag_process has been run successfully.
Additional arguments available besides the import path, user name and verbose:
- `--cutoff_distance "cutoff distance value"`
		specify the maximum gps distance in meters within a sequence
		value type float
		default value 600.0
- `--cutoff_time "cutoff time value"`
		specify the maximum time interval in seconds within a sequence
		value type float
		default value 60.0		
- `--interpolate_directions`
		set True to perform interploation of directions
		note that the values of the derived directions will take precedence of those read from the geotag source
- `--offset_angle	"offset angle value"`	
		specify the offset camera angle (90 for right facing, 180 for rear facing, -90 for left facing)
		value type float
		note in case of direction interpolation, this value will be added to the interpolated directions and not the ones read from the geotag source
- `--flag_duplicates` 
		set True to flag duplicates
		note that duplicates are flagged based on the time elapsed between the images and based on the gps distance between the images
		note that images flagged as duplicated will not be uploaded to Mapillary
- `--duplicate_distance	"duplicate distance value"`	
		specify the max distance for two images to be considered duplicates in meters
		value type float
		default value 0.1
- `--duplicate_angle "duplicate angle value"`
		specify the max angle for two images to be considered duplicates in degrees
		value type float
		default value 5
		
Only the import path is required to run this process tool.		
Usage examples:

    python mapillary_import.py sequence_process path --user_name username_at_mapilary

    python mapillary_import.py sequence_process path --user_name username_at_mapilary --cutoff_distance 1000 --cutoff_time 30 --flag_duplicates 

This unit process is required for an image to be uploaded to Mapillary.
Only skip this process if you have run it already or you do not intent to upload the images to Mapillary.

**insert_EXIF_ImageDescription**
The insert_EXIF_ImageDescription tool will take all the meta data read and processed in the other processing units and insert it in the image EXIF.
No additional arguments available besides the import path, user name and verbose.
Only the import path is required to run this process tool.		
Usage examples:

    python mapillary_import.py insert_EXIF_ImageDescription path

This unit process is required for an image to be uploaded to Mapillary.
Only skip this process if you have run it already or you do not intent to upload the images to Mapillary.
Note that in case other processing units have been run without this processing unit, the updated meta data will not be inserted into image EXIF if skipping or not repeating this process unit.

## Upload

Images that have been successfully processed or were taken with the Mapillary app can be uploaded with the upload tool. 
Either upload alone can be used or process_and_upload.
By default, 4 threads upload in parallel and the script retries 10 times upon encountering a failure. These can be customized with environment variables in the command line:

    NUMBER_THREADS=2 MAX_ATTEMPTS=100

On Android Systems you can find the images under `/storage/emulated/0/Android/data/app.mapillary/files/pictures/`
On iOS, open iTunes, select your device, and scroll down to Mapillary under apps. You can see the files and copy them over from there


**upload**
The upload tool will collect all the images in the import path, while checking for duplicate flags, processing and uploading logs.
If image is flagged as duplicate, was logged with failed process or logged as successfully uploaded, it will not be added to the upload list.


Usage example:

    python mapillary_import.py upload path


**process_and_upload**
The process_and_upload tool will perform both, the process and upload, described above.

Usage example:

    python mapillary_import.py process_and_upload path --user_name username_at_mapilary --add_file_name --add_import_date --device_make Apple --device_model "iPhone SE" --GPS_accuracy 1.5 --cutoff_distance 50 --cutoff_time 120 --interpolate_directions --offset_angle 10 --flag_duplicates --duplicate_distance 2 --duplicate_angle 45 


## Download


Download images from Mapillary


**download_images.py**


Script to download images using the Mapillary image search API. Downloads images inside a rect (min_lat, max_lat, min_lon, max_lon)


    python download_images.py min_lat max_lat min_lon max_lon [--max_results=(max_results)] [--image_size=(320, 640, 1024, or 2048)


## Config


Edit a config file.
If you wish to edit the user specific properties in you config file, below script can be used.
The defualt config file is your global Mapillary config file and will be used if no other file path provided.


**edit_config.py**

	python edit_config.py
	python edit_config.py path



[exifread]: https://pypi.python.org/pypi/ExifRea

[gpxpy]: https://pypi.python.org/pypi/gpxp

[PIL]: https://pypi.python.org/pypi/Pillow/2.2.

[Piexif]: https://github.com/mapillary/Piexi

