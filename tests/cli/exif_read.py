import pprint
import sys
from pathlib import Path

from mapillary_tools.exif_read import ExifRead


if __name__ == "__main__":
    for filename in sys.argv[1:]:
        exif = ExifRead(Path(filename), details=True)
        pprint.pprint(
            {
                "capture_time": exif.extract_capture_time(),
                "gps_time": exif.extract_gps_time(),
                "direction": exif.extract_direction(),
                "model": exif.extract_model(),
                "make": exif.extract_make(),
                "lon_lat": exif.extract_lon_lat(),
                "altitude": exif.extract_altitude(),
            }
        )
