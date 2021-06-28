import os
import typing as T

import requests

from . import processing, api_v4
from . import login


def get_user_properties(
    user_name: str,
    organization_key: T.Optional[str] = None,
    private: bool = False,
) -> T.Optional[T.Dict]:
    # basic
    user_items = login.authenticate_user(user_name)

    if organization_key:
        resp = api_v4.fetch_organization(
            user_items["user_upload_token"], organization_key
        )

        try:
            resp.raise_for_status()
        except requests.RequestException:
            raise RuntimeError(f"Invalid organization {resp.text}")

        org = resp.json()

        print(f"Organization ID: {org['id']}")
        print(f"Organization name: {org['name']}")
        print(f"Organization description: {org['description']}")

        user_items.update(
            {"MAPOrganizationKey": organization_key, "MAPPrivate": private}
        )

    del user_items["user_upload_token"]

    return user_items


def process_user_properties(
    import_path,
    user_name,
    organization_username=None,
    organization_key=None,
    private=False,
    master_upload=False,
    verbose=False,
    rerun=False,
    skip_subfolders=False,
    video_import_path=None,
):
    # sanity check if video file is passed
    if (
        video_import_path
        and not os.path.isdir(video_import_path)
        and not os.path.isfile(video_import_path)
    ):
        raise RuntimeError(
            f"Error, video path {video_import_path} does not exist, exiting..."
        )

    # in case of video processing, adjust the import path
    if video_import_path:
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
        raise RuntimeError(
            f"Error, import directory {import_path} does not exist, exiting..."
        )

    # get list of file to process
    process_file_list = processing.get_process_file_list(
        import_path, "user_process", rerun, verbose, skip_subfolders
    )
    if not process_file_list:
        print("No images to run user process")
        print(
            "If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun"
        )

    # sanity checks
    if not user_name:
        raise RuntimeError("Error, must provide a valid user name, exiting...")

    if private and not organization_username and not organization_key:
        raise RuntimeError(
            "Error, if the import belongs to a private repository, you need to provide a valid organization user name or key to which the private repository belongs to, exiting..."
        )

    user_properties = get_user_properties(
        user_name,
        organization_key,
        private,
    )

    # write data and logs
    processing.create_and_log_process_in_list(
        process_file_list, "user_process", "success", verbose, user_properties
    )
    print("Sub process ended")
