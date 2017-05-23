#!/usr/bin/env python

import os
import argparse

def run(cmd):
    os.system(" ".join(cmd))

def get_args():
    p = argparse.ArgumentParser(description='Sample and geotag video with location and orientation from GPX file.')
    p.add_argument('video_file', help='File path to the data file that contains the metadata')
    p.add_argument('--image_path', help='Path to save sampled images.', default="video_samples")
    p.add_argument('--sample_interval', help='Time interval for sampled frames in seconds', default=1, type=float)
    p.add_argument('--gps_trace', help='GPS track file')
    p.add_argument('--time_offset', help='Time offset between video and gpx file in seconds', default=0, type=float)
    p.add_argument("--skip_sampling", help="Skip video sampling step", action="store_true")
    p.add_argument("--skip_upload", help="Skip upload images", action="store_true")
    p.add_argument("--user", help="User name")
    p.add_argument("--email", help="User email")
    p.add_argument("--project", help="Specify project for the video")

    return p.parse_args()

if __name__ == "__main__":

    args = get_args()

    image_path = os.path.basename(args.video_file).split(".")[0]

    if os.path.exists(os.path.join(image_path, "PROCESSING_LOG.json")) is False:
        cmd = ["python", "geotag_video.py",
               args.video_file,
               "--gps_trace", args.gps_trace,
               "--image_path", image_path,
               "--sample_interval", str(args.sample_interval)]
        run(cmd)

    assert(args.user is not None and args.email is not None)

    if not args.skip_upload:
        upload_cmd = [
            "python", "upload_with_preprocessing.py",
            image_path,
            "--remove_duplicates",
            "--interpolate_directions",
            "--duplicate_distance", "0.5",
            "--duplicate_angle", "360",
            "--user", args.user,
            "--email", args.email,
            "--project", repr(args.project)
        ]
        run(upload_cmd)
