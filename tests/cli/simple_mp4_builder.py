import argparse
import pathlib

from mapillary_tools.geotag import camm_builder, simple_mp4_builder as builder


def main():
    def _parse_args():
        parser = argparse.ArgumentParser()
        parser.add_argument("source_mp4_path", help="where to read the MP4")
        parser.add_argument(
            "target_mp4_path", help="where to write the transformed MP4"
        )
        return parser.parse_args()

    parsed_args = _parse_args()
    builder.transform_mp4(
        pathlib.Path(parsed_args.source_mp4_path),
        pathlib.Path(parsed_args.target_mp4_path),
        camm_builder.camm_sample_generator,
    )


if __name__ == "__main__":
    main()
