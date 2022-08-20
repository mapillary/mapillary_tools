import os

import appdirs

_ENV_PREFIX = "MAPILLARY_TOOLS_"

ANSI_BOLD = "\033[1m"
ANSI_RESET_ALL = "\033[0m"
CUTOFF_DISTANCE = float(os.getenv(_ENV_PREFIX + "CUTOFF_DISTANCE", 600))
CUTOFF_TIME = float(os.getenv(_ENV_PREFIX + "CUTOFF_TIME", 60))
DUPLICATE_DISTANCE = float(os.getenv(_ENV_PREFIX + "DUPLICATE_DISTANCE", 0.1))
DUPLICATE_ANGLE = float(os.getenv(_ENV_PREFIX + "DUPLICATE_ANGLE", 5))
VIDEO_SAMPLE_INTERVAL = float(os.getenv(_ENV_PREFIX + "VIDEO_SAMPLE_INTERVAL", 2))
VIDEO_DURATION_RATIO = float(os.getenv(_ENV_PREFIX + "VIDEO_DURATION_RATIO", 1))
FFPROBE_PATH: str = os.getenv(_ENV_PREFIX + "FFPROBE_PATH", "ffprobe")
FFMPEG_PATH: str = os.getenv(_ENV_PREFIX + "FFMPEG_PATH", "ffmpeg")
IMAGE_DESCRIPTION_FILENAME = os.getenv(
    _ENV_PREFIX + "IMAGE_DESCRIPTION_FILENAME", "mapillary_image_description.json"
)
SAMPLED_VIDEO_FRAMES_FILENAME = os.getenv(
    _ENV_PREFIX + "SAMPLED_VIDEO_FRAMES_FILENAME", "mapillary_sampled_video_frames"
)
MAX_SEQUENCE_LENGTH = int(os.getenv(_ENV_PREFIX + "MAX_SEQUENCE_LENGTH", 500))
USER_DATA_DIR = appdirs.user_data_dir(appname="mapillary_tools", appauthor="Mapillary")
# This is DoP value, the lower the better
# See https://github.com/gopro/gpmf-parser#hero5-black-with-gps-enabled-adds
MAX_GOPRO_GPS_PRECISION = int(os.getenv(_ENV_PREFIX + "MAX_GOPRO_GPS_PRECISION", 1000))
