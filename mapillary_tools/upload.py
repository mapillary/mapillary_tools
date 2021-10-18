import os
import sys
import typing as T
import json
import logging

import requests
from tqdm import tqdm

from . import uploader, types, login, api_v4, ipc

LOG = logging.getLogger(__name__)


def read_image_descriptions(desc_path: str):
    if not os.path.isfile(desc_path):
        raise RuntimeError(
            f"Image description file {desc_path} not found. Please process it first. Exiting..."
        )

    descs: T.List[types.ImageDescriptionJSON] = []
    if desc_path == "-":
        try:
            descs = json.load(sys.stdin)
        except json.JSONDecodeError:
            raise RuntimeError(f"Invalid JSON stream from stdin")
    else:
        with open(desc_path) as fp:
            try:
                descs = json.load(fp)
            except json.JSONDecodeError:
                raise RuntimeError(f" Invalid JSON file {desc_path}")
    descs = [desc for desc in descs if "error" not in desc]
    return descs


def zip_images(
    import_path: str,
    zip_dir: str,
    desc_path: T.Optional[str] = None,
):
    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        raise RuntimeError(f"Error, import directory {import_path} does not exist")

    if desc_path is None:
        desc_path = os.path.join(import_path, "mapillary_image_description.json")

    descs = read_image_descriptions(desc_path)

    if not descs:
        LOG.warning(f"No images found in {desc_path}. Exiting...")
        return

    uploader.zip_image_dir(import_path, descs, zip_dir)


def fetch_user_items(
    user_name: T.Optional[str] = None, organization_key: T.Optional[str] = None
) -> types.User:
    if user_name is None:
        all_user_items = login.list_all_users()
        if not all_user_items:
            raise RuntimeError("No Mapillary account found. Add one with --user_name")
        if len(all_user_items) == 1:
            user_items = all_user_items[0]
        else:
            raise RuntimeError(
                f"Found multiple Mapillary accounts. Please specify one with --user_name"
            )
    else:
        user_items = login.authenticate_user(user_name)

    if organization_key is not None:
        try:
            resp = api_v4.fetch_organization(
                user_items["user_upload_token"], organization_key
            )
        except requests.HTTPError as ex:
            raise login.wrap_http_exception(ex) from ex
        org = resp.json()
        LOG.info(f"Uploading to organization: {json.dumps(org)}")
        user_items = T.cast(
            types.User, {**user_items, "MAPOrganizationKey": organization_key}
        )
    return user_items


upload_pbar: T.Optional[tqdm] = None

emitter = uploader.EventEmitter()


@emitter.on("upload_fetch_offset")
def upload_start(payload: uploader.Progress) -> None:
    global upload_pbar

    if upload_pbar is not None:
        upload_pbar.close()

    nth = payload["sequence_idx"] + 1
    total = payload["total_sequences"]
    upload_pbar = tqdm(
        total=payload["entity_size"],
        desc=f"Uploading ({nth}/{total})",
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        initial=payload["offset"],
    )


@emitter.on("upload_progress")
def upload_progress(stats: uploader.Progress) -> None:
    assert upload_pbar is not None, "progress_bar must be initialized"
    upload_pbar.update(stats["chunk_size"])


@emitter.on("upload_progress")
def upload_ipc_send(payload: uploader.Progress):
    LOG.debug(f"Sending upload progress via IPC: {payload}")
    ipc.send("upload", payload)


@emitter.on("upload_end")
def upload_end(cluster_id: int) -> None:
    global upload_pbar
    if upload_pbar:
        upload_pbar.close()
    upload_pbar = None


def upload(
    import_path: str,
    desc_path: T.Optional[str] = None,
    user_name: T.Optional[str] = None,
    organization_key: T.Optional[str] = None,
    dry_run=False,
):
    if os.path.isfile(import_path):
        _, ext = os.path.splitext(import_path)
        user_items = fetch_user_items(user_name, organization_key)
        if ext.lower() in [".zip"]:
            cluster_id = uploader.Uploader(
                user_items, emitter=emitter, dry_run=dry_run
            ).upload_zipfile(import_path)
        else:
            raise RuntimeError(
                f"Unknown file type {ext}. Currently only BlackVue (.mp4) and ZipFile (.zip) are supported"
            )
        LOG.debug(f"Uploaded to cluster {cluster_id}")

    elif os.path.isdir(import_path):
        if desc_path is None:
            desc_path = os.path.join(import_path, "mapillary_image_description.json")

        descs = read_image_descriptions(desc_path)
        if not descs:
            LOG.warning(f"No images found in {desc_path}")
            return

        user_items = fetch_user_items(user_name, organization_key)

        uploader.Uploader(
            user_items, emitter=emitter, dry_run=dry_run
        ).upload_image_dir(import_path, descs)
    else:
        raise RuntimeError(f"Expect {import_path} to be either file or directory")
