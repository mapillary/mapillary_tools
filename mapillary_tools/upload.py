import datetime
import os
import sys
import typing as T
import json
import logging

import requests
from tqdm import tqdm

from . import uploader, types, login, api_v4, ipc, utils

LOG = logging.getLogger(__name__)
MAPILLARY_DISABLE_API_LOGGING = os.getenv("MAPILLARY_DISABLE_API_LOGGING")


def read_image_descriptions(desc_path: str) -> T.List[types.ImageDescriptionFile]:
    if not os.path.isfile(desc_path):
        raise RuntimeError(
            f"Image description file {desc_path} not found. Please process the image directory first"
        )

    descs: T.List[types.ImageDescriptionFile] = []
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
    return types.filter_out_errors(
        T.cast(T.List[types.ImageDescriptionFileOrError], descs)
    )


def zip_images(
    import_path: str,
    zip_dir: str,
    desc_path: T.Optional[str] = None,
):
    # basic check for all
    if not os.path.isdir(import_path):
        raise RuntimeError(f"Error, import directory {import_path} does not exist")

    if desc_path is None:
        desc_path = os.path.join(import_path, "mapillary_image_description.json")

    descs = read_image_descriptions(desc_path)

    if not descs:
        LOG.warning(f"No images found in {desc_path}")
        return

    uploader.zip_images(_join_desc_path(import_path, descs), zip_dir)


def fetch_user_items(
    user_name: T.Optional[str] = None, organization_key: T.Optional[str] = None
) -> types.UserItem:
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
            types.UserItem, {**user_items, "MAPOrganizationKey": organization_key}
        )
    return user_items


def _setup_tdqm(emitter: uploader.EventEmitter) -> None:
    upload_pbar: T.Optional[tqdm] = None

    @emitter.on("upload_fetch_offset")
    def upload_start(payload: uploader.Progress) -> None:
        nonlocal upload_pbar

        if upload_pbar is not None:
            upload_pbar.close()

        nth = payload["sequence_idx"] + 1
        total = payload["total_sequence_count"]
        upload_pbar = tqdm(
            total=payload["entity_size"],
            desc=f"Uploading ({nth}/{total})",
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            initial=payload["offset"],
            disable=LOG.level <= logging.DEBUG,
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
        nonlocal upload_pbar
        if upload_pbar:
            upload_pbar.close()
        upload_pbar = None


class _Stats(uploader.Progress):
    upload_start_time: datetime.datetime
    upload_end_time: datetime.datetime
    upload_last_restart_time: datetime.datetime
    upload_total_time: float


def _setup_stats(emitter: uploader.EventEmitter):
    all_stats: T.List[_Stats] = []

    @emitter.on("upload_start")
    def collect_start_time(payload: _Stats) -> None:
        payload["upload_start_time"] = datetime.datetime.utcnow()
        payload["upload_total_time"] = 0

    @emitter.on("upload_fetch_offset")
    def collect_restart_time(payload: _Stats) -> None:
        payload["upload_last_restart_time"] = datetime.datetime.utcnow()

    @emitter.on("upload_interrupted")
    def collect_interrupted(payload: _Stats):
        payload["upload_total_time"] += (
            datetime.datetime.utcnow() - payload["upload_last_restart_time"]
        ).total_seconds()

    @emitter.on("upload_end")
    def collect_end_time(payload: _Stats) -> None:
        payload["upload_end_time"] = datetime.datetime.utcnow()
        payload["upload_total_time"] += (
            datetime.datetime.utcnow() - payload["upload_last_restart_time"]
        ).total_seconds()
        all_stats.append(payload)

    return all_stats


def _summarize(stats: T.List[_Stats]) -> T.Dict:
    total_image_count = sum(s.get("sequence_image_count", 0) for s in stats)
    total_sequence_count = len(stats)
    if stats:
        assert total_sequence_count == stats[0]["total_sequence_count"], stats
    total_entity_size = sum(s["entity_size"] for s in stats)
    total_entity_size_mb = total_entity_size / (1024 * 1024)
    total_upload_time = sum(s["upload_total_time"] for s in stats)
    try:
        speed = total_entity_size_mb / total_upload_time
    except ZeroDivisionError:
        speed = 0
    upload_summary = {
        "images": total_image_count,
        "sequences": total_sequence_count,
        "size": round(total_entity_size_mb, 4),
        "speed": round(speed, 4),
        "time": round(total_upload_time, 4),
    }

    return upload_summary


def _api_logging_finished(user_items: types.UserItem, payload: T.Dict):
    if MAPILLARY_DISABLE_API_LOGGING:
        return

    action: api_v4.ActionType = "upload_finished_upload"
    LOG.debug("API Logging for action %s: %s", action, payload)
    try:
        api_v4.logging(
            user_items["user_upload_token"],
            action,
            payload,
        )
    except requests.HTTPError as exc:
        LOG.warning(
            "Error from API Logging for action %s",
            action,
            exc_info=uploader.upload_api_v4.wrap_http_exception(exc),
        )
    except:
        LOG.warning("Error from API Logging for action %s", action, exc_info=True)


def _api_logging_failed(user_items: types.UserItem, payload: T.Dict, exc: Exception):
    if MAPILLARY_DISABLE_API_LOGGING:
        return

    payload_with_reason = {**payload, "reason": exc.__class__.__name__}
    action: api_v4.ActionType = "upload_failed_upload"
    LOG.debug("API Logging for action %s: %s", action, payload)
    try:
        api_v4.logging(
            user_items["user_upload_token"],
            action,
            payload_with_reason,
        )
    except requests.HTTPError as exc:
        wrapped_exc = uploader.upload_api_v4.wrap_http_exception(exc)
        LOG.warning(
            "Error from API Logging for action %s",
            action,
            exc_info=wrapped_exc,
        )
    except:
        LOG.warning("Error from API Logging for action %s", action, exc_info=True)


def _join_desc_path(
    image_dir: str, descs: T.List[types.ImageDescriptionFile]
) -> T.List[types.ImageDescriptionFile]:
    return [
        T.cast(
            types.ImageDescriptionFile,
            {**d, "filename": os.path.join(image_dir, d["filename"])},
        )
        for d in descs
    ]


def upload(
    import_path: str,
    desc_path: T.Optional[str] = None,
    user_name: T.Optional[str] = None,
    organization_key: T.Optional[str] = None,
    dry_run=False,
):
    emitter = uploader.EventEmitter()
    _setup_tdqm(emitter)

    # now it is empty but it will collect during upload
    stats = _setup_stats(emitter)

    if os.path.isfile(import_path):
        _, ext = os.path.splitext(import_path)
        user_items = fetch_user_items(user_name, organization_key)
        mly_uploader = cluster_id = uploader.Uploader(
            user_items, emitter=emitter, dry_run=dry_run
        )
        if ext.lower() in [".zip"]:
            try:
                mly_uploader.upload_zipfile(import_path)
            except Exception as exc:
                if not dry_run:
                    _api_logging_failed(user_items, _summarize(stats), exc)
                raise
        elif ext.lower() in [".mp4"]:
            try:
                mly_uploader.upload_blackvue(import_path)
            except Exception as exc:
                if not dry_run:
                    _api_logging_failed(user_items, _summarize(stats), exc)
                raise
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

        mly_uploader = uploader.Uploader(user_items, emitter=emitter, dry_run=dry_run)
        try:
            mly_uploader.upload_images(_join_desc_path(import_path, descs))
        except Exception as exc:
            if not dry_run:
                _api_logging_failed(user_items, _summarize(stats), exc)
            raise
    else:
        raise RuntimeError(f"Expect {import_path} to be either file or directory")

    upload_summary = _summarize(stats)

    LOG.info(
        "Upload summary (in megabytes/second): %s", json.dumps(upload_summary, indent=4)
    )
    if not dry_run:
        _api_logging_finished(user_items, upload_summary)
