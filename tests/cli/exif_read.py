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
        pprint.pprint(exif.tags)
        pprint.pprint(
            {
                "filename": image_path,
                "altitude": exif.extract_altitude(),
                "capture_time": exif.extract_capture_time(),
                "direction": exif.extract_direction(),
                "exif_time": exif.extract_exif_datetime(),
                "gps_time": exif.extract_gps_datetime(),
                "lon_lat": exif.extract_lon_lat(),
                "make": exif.extract_make(),
                "model": exif.extract_model(),
                "width": exif.extract_width(),
                "height": exif.extract_height(),
            }
        )
        xmp = exif.extract_xmp()
        if xmp is not None:
            pprint.pprint(
                {
                    "filename": image_path,
                    "altitude": xmp.extract_altitude(),
                    "capture_time": xmp.extract_capture_time(),
                    "direction": xmp.extract_direction(),
                    "gps_time": xmp.extract_gps_datetime(),
                    "lon_lat": xmp.extract_lon_lat(),
                    "make": xmp.extract_make(),
                    "model": xmp.extract_model(),
                    "width": xmp.extract_width(),
                    "height": xmp.extract_height(),
                }
            )


if __name__ == "__main__":
    main()
