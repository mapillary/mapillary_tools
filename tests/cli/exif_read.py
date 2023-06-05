import argparse
import pprint
import sys
import xml.etree.ElementTree as et
from pathlib import Path

from mapillary_tools import utils
from mapillary_tools.exif_read import ExifRead, ExifReadABC
from mapillary_tools.exiftool_read import EXIFTOOL_NAMESPACES, ExifToolRead


def extract_and_show_exif(image_path):
    print(f"======== ExifRead Output {image_path} ========")
    try:
        exif = ExifRead(image_path)
    except Exception as ex:
        print(f"Error: {ex}")
        return
    not_interested = ["JPEGThumbnail", "Image ImageDescription"]
    for tag in not_interested:
        if tag in exif.tags:
            del exif.tags[tag]
    pprint.pprint(exif.tags)
    pprint.pprint(as_dict(exif))


def as_dict(exif: ExifReadABC):
    return {
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
        "orientation": exif.extract_orientation(),
    }


def _round(v):
    if isinstance(v, float):
        return round(v, 6)
    elif isinstance(v, tuple):
        return tuple(round(x, 6) for x in v)
    else:
        return v


def compare_exif(left: dict, right: dict) -> bool:
    RED_COLOR = "\x1b[31;20m"
    RESET_COLOR = "\x1b[0m"
    diff = False
    for key in left:
        if key in ["width", "height"]:
            continue
        if key in ["lon_lat", "altitude", "direction"]:
            left_value = _round(left[key])
            right_value = _round(right[key])
        else:
            left_value = left[key]
            right_value = right[key]
        if left_value != right_value:
            print(f"{RED_COLOR}{key}: {left_value} != {right_value}{RESET_COLOR}")
            diff = True
    return diff


def extract_and_show_from_exiftool(fp, compare: bool = False):
    etree = et.parse(fp)
    descriptions = etree.findall(".//rdf:Description", namespaces=EXIFTOOL_NAMESPACES)
    for description in descriptions:
        exif = ExifToolRead(et.ElementTree(description))
        dir = description.findtext("./System:Directory", namespaces=EXIFTOOL_NAMESPACES)
        filename = description.findtext(
            "./System:FileName", namespaces=EXIFTOOL_NAMESPACES
        )
        image_path = Path(dir or "", filename or "")
        if compare:
            native_exif = ExifRead(image_path)
            diff = compare_exif(as_dict(exif), as_dict(native_exif))
            if diff:
                print(f"======== ExifTool Outuput {image_path} ========")
                pprint.pprint(as_dict(exif))
                print(f"======== ExifRead Output {image_path} ========")
                pprint.pprint(as_dict(native_exif))
        else:
            print(f"======== ExifTool Outuput {image_path} ========")
            pprint.pprint(as_dict(exif))


def namespace(tag):
    for ns, val in EXIFTOOL_NAMESPACES.items():
        if tag.startswith("{" + val + "}"):
            return ns + ":" + tag[len(val) + 2 :]
    return tag


def list_tags(fp):
    etree = et.parse(fp)
    descriptions = etree.findall(".//rdf:Description", namespaces=EXIFTOOL_NAMESPACES)
    tags = set()
    for description in descriptions:
        for child in description.iter():
            tags.add(child.tag)
    for tag in sorted(tags):
        print(namespace(tag))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="*")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--list_keys", action="store_true")
    parsed_args = parser.parse_args()
    if not parsed_args.path:
        if parsed_args.list_keys:
            list_tags(sys.stdin)
        else:
            extract_and_show_from_exiftool(sys.stdin, parsed_args.compare)
    else:
        for image_path in utils.find_images([Path(p) for p in parsed_args.path]):
            extract_and_show_exif(image_path)


if __name__ == "__main__":
    main()
