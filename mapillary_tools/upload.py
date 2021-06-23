import os
import sys
import typing as T


from . import uploader, processing, types


def list_image_descriptions_for_upload(
    import_path: str, skip_subfolders: bool
) -> T.Dict[str, types.FinalImageDescription]:
    filtered = {}
    images = uploader.get_total_file_list(import_path, skip_subfolders)
    for image in images:
        if uploader.success_upload(image):
            continue
        desc = processing.read_image_description(image)
        if desc is None:
            continue
        filtered[image] = desc

    return filtered


def upload(
    import_path,
    skip_subfolders=False,
    video_import_path=None,
    dry_run=False,
):
    # in case of video processing, adjust the import path
    if video_import_path:
        # sanity check if video file is passed
        if not os.path.isdir(video_import_path) and not os.path.isfile(
            video_import_path
        ):
            print(f"Error, video path {video_import_path} does not exist, exiting...")
            sys.exit(1)

        # set sampling path
        video_sampling_path = "mapillary_sampled_video_frames"
        video_dirname = (
            video_import_path
            if os.path.isdir(video_import_path)
            else os.path.dirname(video_import_path)
        )
        import_path = (
            os.path.join(os.path.abspath(import_path), video_sampling_path)
            if import_path
            else os.path.join(os.path.abspath(video_dirname), video_sampling_path)
        )

    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        print(f"Error, import directory {import_path} does not exist, exiting...")
        sys.exit(1)

    image_descriptions = list_image_descriptions_for_upload(
        import_path, skip_subfolders
    )

    uploader.upload_images(image_descriptions, dry_run=dry_run)
