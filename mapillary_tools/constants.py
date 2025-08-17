from __future__ import annotations

import functools
import os
import tempfile

import appdirs

_ENV_PREFIX = "MAPILLARY_TOOLS_"


def _yes_or_no(val: str) -> bool:
    return val.strip().upper() in ["1", "TRUE", "YES"]


def _parse_scaled_integers(
    value: str, scale: dict[str, int] | None = None
) -> int | None:
    """
    >>> scale = {"": 1, "b": 1, "K": 1024, "M": 1024 * 1024, "G": 1024 * 1024 * 1024}
    >>> _parse_scaled_integers("0", scale=scale)
    0
    >>> _parse_scaled_integers("10", scale=scale)
    10
    >>> _parse_scaled_integers("100B", scale=scale)
    100
    >>> _parse_scaled_integers("100k", scale=scale)
    102400
    >>> _parse_scaled_integers("100t", scale=scale)
    Traceback (most recent call last):
    ValueError: Expect valid integer ends with , b, K, M, G, but got 100T
    """

    if scale is None:
        scale = {"": 1}

    value = value.strip().upper()

    if value in ["INF", "INFINITY"]:
        return None

    try:
        for k, v in scale.items():
            k = k.upper()
            if k and value.endswith(k):
                return int(value[: -len(k)]) * v

        if "" in scale:
            return int(value) * scale[""]
    except ValueError:
        pass

    raise ValueError(
        f"Expect valid integer ends with {', '.join(scale.keys())}, but got {value}"
    )


_parse_pixels = functools.partial(
    _parse_scaled_integers,
    scale={
        "": 1,
        "K": 1000,
        "M": 1000 * 1000,
        "MP": 1000 * 1000,
        "G": 1000 * 1000 * 1000,
        "GP": 1000 * 1000 * 1000,
    },
)

_parse_filesize = functools.partial(
    _parse_scaled_integers,
    scale={"B": 1, "K": 1024, "M": 1024 * 1024, "G": 1024 * 1024 * 1024},
)

###################
##### GENERAL #####
###################
USER_DATA_DIR = appdirs.user_data_dir(appname="mapillary_tools", appauthor="Mapillary")
PROMPT_DISABLED: bool = _yes_or_no(os.getenv(_ENV_PREFIX + "PROMPT_DISABLED", "NO"))


############################
##### VIDEO PROCESSING #####
############################
# In seconds
VIDEO_SAMPLE_INTERVAL = float(os.getenv(_ENV_PREFIX + "VIDEO_SAMPLE_INTERVAL", -1))
# In meters
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
# DoP value, the lower the better
# See https://github.com/gopro/gpmf-parser#hero5-black-with-gps-enabled-adds
# It is used to filter out noisy points
GOPRO_MAX_DOP100 = int(os.getenv(_ENV_PREFIX + "GOPRO_MAX_DOP100", 1000))
# Within the GPS stream: 0 - no lock, 2 or 3 - 2D or 3D Lock
GOPRO_GPS_FIXES: set[int] = set(
    int(fix) for fix in os.getenv(_ENV_PREFIX + "GOPRO_GPS_FIXES", "2,3").split(",")
)
# GPS precision, in meters, is used to filter outliers
GOPRO_GPS_PRECISION = float(os.getenv(_ENV_PREFIX + "GOPRO_GPS_PRECISION", 15))
MAPILLARY__EXPERIMENTAL_ENABLE_IMU: bool = _yes_or_no(
    os.getenv("MAPILLARY__EXPERIMENTAL_ENABLE_IMU", "NO")
)


#################################
###### SEQUENCE PROCESSING ######
#################################
# In meters
CUTOFF_DISTANCE = float(os.getenv(_ENV_PREFIX + "CUTOFF_DISTANCE", 600))
# In seconds
CUTOFF_TIME = float(os.getenv(_ENV_PREFIX + "CUTOFF_TIME", 60))
DUPLICATE_DISTANCE = float(os.getenv(_ENV_PREFIX + "DUPLICATE_DISTANCE", 0.1))
DUPLICATE_ANGLE = float(os.getenv(_ENV_PREFIX + "DUPLICATE_ANGLE", 5))
MAX_CAPTURE_SPEED_KMH = float(
    os.getenv(_ENV_PREFIX + "MAX_CAPTURE_SPEED_KMH", 400)
)  # 400 KM/h
# WARNING: Changing the following envvars might result in failed uploads
# Max number of images per sequence
MAX_SEQUENCE_LENGTH: int | None = _parse_scaled_integers(
    os.getenv(_ENV_PREFIX + "MAX_SEQUENCE_LENGTH", "1000")
)
# Max file size per sequence (sum of image filesizes in the sequence)
MAX_SEQUENCE_FILESIZE: int | None = _parse_filesize(
    os.getenv(_ENV_PREFIX + "MAX_SEQUENCE_FILESIZE", "110G")
)
# Max number of pixels per sequence (sum of image pixels in the sequence)
MAX_SEQUENCE_PIXELS: int | None = _parse_pixels(
    os.getenv(_ENV_PREFIX + "MAX_SEQUENCE_PIXELS", "6G")
)


##################
##### UPLOAD #####
##################
MAPILLARY_DISABLE_API_LOGGING: bool = _yes_or_no(
    os.getenv("MAPILLARY_DISABLE_API_LOGGING", "NO")
)
MAPILLARY_UPLOAD_HISTORY_PATH: str = os.getenv(
    "MAPILLARY_UPLOAD_HISTORY_PATH", os.path.join(USER_DATA_DIR, "upload_history")
)
UPLOAD_CACHE_DIR: str = os.getenv(
    _ENV_PREFIX + "UPLOAD_CACHE_DIR",
    os.path.join(tempfile.gettempdir(), "mapillary_tools", "upload_cache"),
)
# The minimal upload speed is used to calculate the read timeout to avoid upload hanging:
# timeout = upload_size / MIN_UPLOAD_SPEED
MIN_UPLOAD_SPEED: int | None = _parse_filesize(
    os.getenv(_ENV_PREFIX + "MIN_UPLOAD_SPEED", "50K")  # 50 Kb/s
)
# Maximum number of parallel workers for uploading images within a single sequence.
# NOTE: Sequences themselves are uploaded sequentially, not in parallel.
MAX_IMAGE_UPLOAD_WORKERS: int = int(
    os.getenv(_ENV_PREFIX + "MAX_IMAGE_UPLOAD_WORKERS", 4)
)
# The chunk size in MB (see chunked transfer encoding https://en.wikipedia.org/wiki/Chunked_transfer_encoding)
# for uploading data to MLY upload service.
# Changing this size does not change the number of requests nor affect upload performance,
# but it affects the responsiveness of the upload progress bar
UPLOAD_CHUNK_SIZE_MB: float = float(os.getenv(_ENV_PREFIX + "UPLOAD_CHUNK_SIZE_MB", 2))
MAX_UPLOAD_RETRIES: int = int(os.getenv(_ENV_PREFIX + "MAX_UPLOAD_RETRIES", 200))
MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN: bool = _yes_or_no(
    os.getenv("MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN", "NO")
)
_AUTH_VERIFICATION_DISABLED: bool = _yes_or_no(
    os.getenv(_ENV_PREFIX + "_AUTH_VERIFICATION_DISABLED", "NO")
)
