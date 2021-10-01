import os
import sys
import typing as T
import json
import logging

import requests

from . import image_log
from . import uploader, types, login, api_v4

LOG = logging.getLogger()


def list_image_descriptions_for_upload(
    import_path: str,
    descs: T.List[types.FinalImageDescription],
    skip_subfolders: bool = False,
) -> T.Dict[str, types.FinalImageDescription]:
    filtered = {}
    index: T.Dict[str, types.FinalImageDescription] = {}
    for desc in descs:
        index[desc["_filename"]] = desc

    images = image_log.get_total_file_list(import_path, skip_subfolders)
    for image in images:
        relpath = os.path.relpath(image, import_path)
        final_desc = index.get(relpath)
        if final_desc is None:
            continue
        filtered[relpath] = final_desc

    return filtered


def upload(
    import_path: str,
    desc_path: T.Optional[str] = None,
    user_name: T.Optional[str] = None,
    organization_key: T.Optional[str] = None,
    skip_subfolders=False,
    dry_run=False,
):
    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        raise RuntimeError(
            f"Error, import directory {import_path} does not exist, exiting..."
        )

    if desc_path is None:
        desc_path = os.path.join(import_path, "mapillary_image_description.json")

    if desc_path == "-":
        descs = json.load(sys.stdin)
    else:
        with open(desc_path) as fp:
            descs = json.load(fp)

    descs = [desc for desc in descs if "error" not in desc]

    image_descriptions = list_image_descriptions_for_upload(
        import_path,
        descs,
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

        LOG.info(f"Organization ID: {org['id']}")
        LOG.info(f"Organization name: {org['name']}")
        LOG.info(f"Organization description: {org['description']}")

        user_items.update({"MAPOrganizationKey": organization_key})

    uploader.upload_images(import_path, image_descriptions, user_items, dry_run=dry_run)
