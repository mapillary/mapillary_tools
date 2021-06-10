import os

VERSION = "0.7.0"

MAPILLARY_API_VERSION = os.getenv("MAPILLARY_API_VERSION", "v4")
assert MAPILLARY_API_VERSION in [
    "v3",
    "v4",
], "MAPILLARY_API_VERSION must be either v3 or v4"
