import argparse
import io
import piexif

from PIL import Image


def parse_args():
    parser = argparse.ArgumentParser(description='Generate a test image by transplanting exif')
    parser.add_argument('input_image', help='path to imput image containing exif')
    parser.add_argument('output_image', help='path to generated output image')

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    with open(args.input_image, "rb") as fin:
        input_string = fin.read()

    Image.new("RGB", (16, 16), (255, 0, 0)).save(args.output_image)
    with open(args.output_image, "rb") as f:
        image_string = f.read()

    output_bytes = io.BytesIO()
    piexif.transplant(input_string, image_string, output_bytes)

    with open(args.output_image, "w") as fout:
        fout.write(output_bytes.read())
