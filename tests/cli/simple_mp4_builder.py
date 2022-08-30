import argparse

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

    with open(parsed_args.source_mp4_path, "rb") as src_fp:
        with open(parsed_args.target_mp4_path, "wb") as tar_fp:
            builder.transform_mp4(
                src_fp,
                tar_fp,
                camm_builder.camm_sample_generator,
            )


if __name__ == "__main__":
    main()
