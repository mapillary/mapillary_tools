import argparse
from pathlib import Path

from mapillary_tools import process_geotag_properties

from mapillary_tools.geotag import camm_builder, simple_mp4_builder as builder


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_mp4_path", help="where to read the MP4")
    parser.add_argument("target_mp4_path", help="where to write the transformed MP4")
    return parser.parse_args()


def main():
    parsed_args = _parse_args()
    video_metadata = process_geotag_properties.process_video(
        Path(parsed_args.source_mp4_path)
    )
    generator = camm_builder.camm_sample_generator2(video_metadata)
    with open(parsed_args.source_mp4_path, "rb") as src_fp:
        with open(parsed_args.target_mp4_path, "wb") as tar_fp:
            reader = builder.transform_mp4(
                src_fp,
                generator,
            )
            while True:
                data = reader.read(1024 * 1024 * 64)
                if not data:
                    break
                tar_fp.write(data)


if __name__ == "__main__":
    main()
