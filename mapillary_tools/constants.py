import os
import typing as T

import appdirs

_ENV_PREFIX = "MAPILLARY_TOOLS_"

ANSI_BOLD = "\033[1m"
ANSI_RESET_ALL = "\033[0m"
CUTOFF_DISTANCE = float(os.getenv(_ENV_PREFIX + "CUTOFF_DISTANCE", 600))
CUTOFF_TIME = float(os.getenv(_ENV_PREFIX + "CUTOFF_TIME", 60))
DUPLICATE_DISTANCE = float(os.getenv(_ENV_PREFIX + "DUPLICATE_DISTANCE", 0.1))
DUPLICATE_ANGLE = float(os.getenv(_ENV_PREFIX + "DUPLICATE_ANGLE", 5))
# in seconds
VIDEO_SAMPLE_INTERVAL = float(os.getenv(_ENV_PREFIX + "VIDEO_SAMPLE_INTERVAL", -1))
# in meters
VIDEO_SAMPLE_DISTANCE = float(os.getenv(_ENV_PREFIX + "VIDEO_SAMPLE_DISTANCE", 3))
VIDEO_DURATION_RATIO = float(os.getenv(_ENV_PREFIX + "VIDEO_DURATION_RATIO", 1))
FFPROBE_PATH: str = os.getenv(_ENV_PREFIX + "FFPROBE_PATH", "ffprobe")
FFMPEG_PATH: str = os.getenv(_ENV_PREFIX + "FFMPEG_PATH", "ffmpeg")
EXIFTOOL_PATH: str = os.getenv(_ENV_PREFIX + "EXIFTOOL_PATH", "exiftool")
IMAGE_DESCRIPTION_FILENAME = os.getenv(
    _ENV_PREFIX + "IMAGE_DESCRIPTION_FILENAME", "mapillary_image_description.json"
)
SAMPLED_VIDEO_FRAMES_FILENAME = os.getenv(
    _ENV_PREFIX + "SAMPLED_VIDEO_FRAMES_FILENAME", "mapillary_sampled_video_frames"
)
USER_DATA_DIR = appdirs.user_data_dir(appname="mapillary_tools", appauthor="Mapillary")
UPLOAD_CHUNK_SIZE_MB = float(os.getenv(_ENV_PREFIX + "UPLOAD_CHUNK_SIZE_MB", 16))

# DoP value, the lower the better
# See https://github.com/gopro/gpmf-parser#hero5-black-with-gps-enabled-adds
# It is used to filter out noisy points
GOPRO_MAX_DOP100 = int(os.getenv(_ENV_PREFIX + "GOPRO_MAX_DOP100", 1000))
# Within the GPS stream: 0 - no lock, 2 or 3 - 2D or 3D Lock
GOPRO_GPS_FIXES: T.Set[int] = set(
    int(fix) for fix in os.getenv(_ENV_PREFIX + "GOPRO_GPS_FIXES", "2,3").split(",")
)
MAX_UPLOAD_RETRIES: int = int(os.getenv(_ENV_PREFIX + "MAX_UPLOAD_RETRIES", 200))

# GPS precision, in meters, is used to filter outliers
GOPRO_GPS_PRECISION = float(os.getenv(_ENV_PREFIX + "GOPRO_GPS_PRECISION", 15))

# WARNING: Changing the following envvars might result in failed uploads
# Max number of images per sequence
MAX_SEQUENCE_LENGTH = int(os.getenv(_ENV_PREFIX + "MAX_SEQUENCE_LENGTH", 1000))
# Max file size per sequence (sum of image filesizes in the sequence)
MAX_SEQUENCE_FILESIZE: str = os.getenv(_ENV_PREFIX + "MAX_SEQUENCE_FILESIZE", "110G")
# Max number of pixels per sequence (sum of image pixels in the sequence)
MAX_SEQUENCE_PIXELS: str = os.getenv(_ENV_PREFIX + "MAX_SEQUENCE_PIXELS", "6G")
