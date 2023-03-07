import argparse
import pprint
from pathlib import Path

from mapillary_tools import utils

from mapillary_tools.exif_read import ExifRead


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="+")
    parsed_args = parser.parse_args()
    for image_path in utils.find_images([Path(p) for p in parsed_args.path]):
        exif = ExifRead(image_path, details=True)
        pprint.pprint(
            {
                "filename": image_path,
                "capture_time": exif.extract_capture_time(),
                "gps_time": exif.extract_gps_datetime(),
                "direction": exif.extract_direction(),
                "model": exif.extract_model(),
                "make": exif.extract_make(),
                "lon_lat": exif.extract_lon_lat(),
                "altitude": exif.extract_altitude(),
            }
        )


if __name__ == "__main__":
    main()
