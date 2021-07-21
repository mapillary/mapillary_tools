import os
import sys
import typing as T
import json

import requests

from . import uploader, processing, types, login, api_v4, geojson


def list_image_descriptions_for_upload(
    import_path: str,
    geojson_source: T.Optional[dict] = None,
    skip_subfolders: bool = False,
) -> T.Dict[str, types.FinalImageDescription]:
    filtered = {}
    index = {}
    if geojson_source is not None:
        descs = geojson.feature_collection_to_desc(geojson_source)
        for desc in descs:
            index[desc["_filename"]] = desc

    images = uploader.get_total_file_list(import_path, skip_subfolders)
    for image in images:
        if uploader.success_upload(image):
            continue

        if geojson_source is None:
            desc = processing.read_image_description(image)
        else:
            desc = index.get(image)

        if desc is None:
            continue

        filtered[image] = desc

    return filtered


def upload(
    import_path: str,
    read_geojson: T.Optional[str] = None,
    user_name: T.Optional[str] = None,
    organization_key: T.Optional[str] = None,
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

    geojson_source: T.Optional[dict] = None
    if read_geojson is not None:
        if read_geojson == "-":
            geojson_source = json.load(sys.stdin)
            pass
        else:
            with open(read_geojson) as fp:
                geojson_source = json.load(fp)

    image_descriptions = list_image_descriptions_for_upload(
        import_path,
        geojson_source=geojson_source,
        skip_subfolders=skip_subfolders,
    )

    if not image_descriptions:
        print("No images for upload")
        return

    if user_name is None:
        all_user_items = login.list_all_users()
        if not all_user_items:
            raise RuntimeError(
                "Not Mapillary account found in the system. Add one with --user_name"
            )
        if len(all_user_items) == 1:
            user_items = all_user_items[0]
        else:
            raise RuntimeError(
                f"There are multiple accounts in your config. Specify one with --user_name"
            )
    else:
        user_items = login.authenticate_user(user_name)

    if organization_key:
        resp = api_v4.fetch_organization(
            user_items["user_upload_token"], organization_key
        )

        try:
            resp.raise_for_status()
        except requests.HTTPError as ex:
            raise login.wrap_http_exception(ex) from ex

        org = resp.json()

        print(f"Organization ID: {org['id']}")
        print(f"Organization name: {org['name']}")
        print(f"Organization description: {org['description']}")

        user_items.update({"MAPOrganizationKey": organization_key})

    uploader.upload_images(image_descriptions, user_items, dry_run=dry_run)
