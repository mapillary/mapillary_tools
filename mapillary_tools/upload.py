import os
import sys
import typing as T
import json
import logging
import time
import uuid
import string

if sys.version_info >= (3, 8):
    from typing import Literal  # pylint: disable=no-name-in-module
else:
    from typing_extensions import Literal

import requests
from tqdm import tqdm

from . import uploader, types, login, api_v4, ipc, config

LOG = logging.getLogger(__name__)
MAPILLARY_DISABLE_API_LOGGING = os.getenv("MAPILLARY_DISABLE_API_LOGGING")
MAPILLARY_UPLOAD_HISTORY_PATH = os.getenv(
    "MAPILLARY_UPLOAD_HISTORY_PATH",
    # To enable it by default
    # os.path.join(config.DEFAULT_MAPILLARY_FOLDER, "upload_history"),
)


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


EventName = Literal[
    "upload_start", "upload_fetch_offset", "upload_progress", "upload_end"
]


def _validate_hexdigits(md5sum: str):
    try:
        assert set(md5sum).issubset(string.hexdigits)
        assert 4 <= len(md5sum)
        _ = int(md5sum, 16)
    except Exception:
        raise ValueError(f"Invalid md5sum {md5sum}")


def _history_desc_path(md5sum: str) -> str:
    assert MAPILLARY_UPLOAD_HISTORY_PATH is not None
    _validate_hexdigits(md5sum)
    subfolder = md5sum[:2]
    assert subfolder, f"Invalid md5sum {md5sum}"
    basename = md5sum[2:]
    assert basename, f"Invalid md5sum {md5sum}"
    return os.path.join(MAPILLARY_UPLOAD_HISTORY_PATH, subfolder, f"{basename}.json")


def is_uploaded(md5sum: str) -> bool:
    if MAPILLARY_UPLOAD_HISTORY_PATH is None:
        return False
    return os.path.isfile(_history_desc_path(md5sum))


def write_history(
    md5sum: str,
    params: T.Dict,
    summary: T.Dict,
    descs: T.Optional[T.List[types.ImageDescriptionFile]] = None,
) -> None:
    if MAPILLARY_UPLOAD_HISTORY_PATH is None:
        return
    path = _history_desc_path(md5sum)
    LOG.debug(f"Writing upload history at {path}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    history: T.Dict = {
        "params": params,
        "summary": summary,
    }
    if descs is not None:
        history["descs"] = descs
    with open(path, "w") as fp:
        fp.write(json.dumps(history))


def _setup_cancel_due_to_duplication(emitter: uploader.EventEmitter) -> None:
    @emitter.on("upload_start")
    def upload_start(payload: uploader.Progress):
        md5sum = payload["md5sum"]
        if is_uploaded(md5sum):
            sequence_uuid = payload.get("sequence_uuid")
            if sequence_uuid is None:
                basename = os.path.basename(payload.get("import_path", ""))
                LOG.info(
                    f"File {basename} has been uploaded already. Check the upload history at {_history_desc_path(md5sum)}"
                )
            else:
                LOG.info(
                    f"Sequence {sequence_uuid} has been uploaded already. Check the upload history at {_history_desc_path(md5sum)}"
                )
            raise uploader.UploadCancelled()


def _setup_write_upload_history(
    emitter: uploader.EventEmitter,
    params: T.Dict,
    descs: T.Optional[T.List[types.ImageDescriptionFile]] = None,
) -> None:
    @emitter.on("upload_finished")
    def upload_finished(payload: uploader.Progress):
        sequence_uuid = payload.get("sequence_uuid")
        md5sum = payload["md5sum"]
        if sequence_uuid is None or descs is None:
            sequence = None
        else:
            sequence = [
                desc for desc in descs if desc.get("MAPSequenceUUID") == sequence_uuid
            ]
            sequence.sort(
                key=lambda d: types.map_capture_time_to_datetime(d["MAPCaptureTime"])
            )

        try:
            write_history(
                md5sum,
                params,
                T.cast(T.Dict, payload),
                sequence,
            )
        except OSError:
            LOG.warning(f"Error writing upload history {md5sum}", exc_info=True)


def _setup_tdqm(emitter: uploader.EventEmitter) -> None:
    upload_pbar: T.Optional[tqdm] = None

    @emitter.on("upload_fetch_offset")
    def upload_fetch_offset(payload: uploader.Progress) -> None:
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
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        )

    @emitter.on("upload_progress")
    def upload_progress(payload: uploader.Progress) -> None:
        assert upload_pbar is not None, "progress_bar must be initialized"
        upload_pbar.update(payload["chunk_size"])

    @emitter.on("upload_end")
    def upload_end(cluster_id: int) -> None:
        nonlocal upload_pbar
        if upload_pbar:
            upload_pbar.close()
        upload_pbar = None


def _setup_ipc(emitter: uploader.EventEmitter):
    @emitter.on("upload_start")
    def upload_start(payload: uploader.Progress):
        type: EventName = "upload_start"
        LOG.debug(f"Sending {type} via IPC: {payload}")
        ipc.send(type, payload)

    @emitter.on("upload_fetch_offset")
    def upload_fetch_offset(payload: uploader.Progress) -> None:
        type: EventName = "upload_fetch_offset"
        LOG.debug(f"Sending {type} via IPC: {payload}")
        ipc.send(type, payload)

    @emitter.on("upload_progress")
    def upload_progress(payload: uploader.Progress):
        type: EventName = "upload_progress"
        LOG.debug(f"Sending {type} via IPC: {payload}")
        ipc.send(type, payload)

    @emitter.on("upload_end")
    def upload_end(payload: uploader.Progress) -> None:
        type: EventName = "upload_end"
        LOG.debug(f"Sending {type} via IPC: {payload}")
        ipc.send(type, payload)


class _APIStats(uploader.Progress):
    # timestamp on upload_start
    upload_start_time: float

    # timestamp on upload_end
    upload_end_time: float

    # timestamp on upload_fetch_offset
    upload_last_restart_time: float

    # total time without time waiting for retries
    upload_total_time: float

    # first offset (used to calculate the total uploaded size)
    upload_first_offset: int


def _setup_api_stats(emitter: uploader.EventEmitter):
    all_stats: T.List[_APIStats] = []

    @emitter.on("upload_start")
    def collect_start_time(payload: _APIStats) -> None:
        payload["upload_start_time"] = time.time()
        payload["upload_total_time"] = 0

    @emitter.on("upload_fetch_offset")
    def collect_restart_time(payload: _APIStats) -> None:
        payload["upload_last_restart_time"] = time.time()
        payload["upload_first_offset"] = min(
            payload["offset"], payload.get("upload_first_offset", payload["offset"])
        )

    @emitter.on("upload_interrupted")
    def collect_interrupted(payload: _APIStats):
        payload["upload_total_time"] += (
            time.time() - payload["upload_last_restart_time"]
        )

    @emitter.on("upload_end")
    def collect_end_time(payload: _APIStats) -> None:
        now = time.time()
        payload["upload_end_time"] = now
        payload["upload_total_time"] += now - payload["upload_last_restart_time"]
        all_stats.append(payload)

    return all_stats


def _summarize(stats: T.List[_APIStats]) -> T.Dict:
    total_image_count = sum(s.get("sequence_image_count", 0) for s in stats)
    total_uploaded_sequence_count = len(stats)
    # note that stats[0]["total_sequence_count"] not always same as total_uploaded_sequence_count

    total_uploaded_size = sum(
        s["entity_size"] - s["upload_first_offset"] for s in stats
    )
    total_uploaded_size_mb = total_uploaded_size / (1024 * 1024)

    total_upload_time = sum(s["upload_total_time"] for s in stats)
    try:
        speed = total_uploaded_size_mb / total_upload_time
    except ZeroDivisionError:
        speed = 0

    total_entity_size = sum(s["entity_size"] for s in stats)
    total_entity_size_mb = total_entity_size / (1024 * 1024)

    upload_summary = {
        "images": total_image_count,
        "sequences": total_uploaded_sequence_count,
        "size": round(total_entity_size_mb, 4),
        "uploaded_size": round(total_uploaded_size_mb, 4),
        "speed": round(speed, 4),
        "time": round(total_upload_time, 4),
    }

    return upload_summary


def _api_logging_finished(user_items: types.UserItem, summary: T.Dict):
    if MAPILLARY_DISABLE_API_LOGGING:
        return

    action: api_v4.ActionType = "upload_finished_upload"
    LOG.debug("API Logging for action %s: %s", action, summary)
    try:
        api_v4.logging(
            user_items["user_upload_token"],
            action,
            summary,
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

    # Setup the emitter -- the order matters here

    # Put it first one to cancel early
    _setup_cancel_due_to_duplication(emitter)

    # This one set up tdqm
    _setup_tdqm(emitter)

    # Now stats is empty but it will collect during upload
    stats = _setup_api_stats(emitter)

    # Send the progress as well as the log stats collected above
    _setup_ipc(emitter)

    params = {
        "import_path": import_path,
        "desc_path": desc_path,
        "user_name": user_name,
        "organization_key": organization_key,
    }

    if os.path.isfile(import_path):
        _, ext = os.path.splitext(import_path)
        user_items = fetch_user_items(user_name, organization_key)
        if not dry_run:
            _setup_write_upload_history(emitter, params)
        mly_uploader = uploader.Uploader(user_items, emitter=emitter, dry_run=dry_run)
        if ext.lower() in [".zip"]:
            try:
                cluster_id = mly_uploader.upload_zipfile(import_path)
            except Exception as exc:
                if not dry_run:
                    _api_logging_failed(user_items, _summarize(stats), exc)
                raise
        elif ext.lower() in [".mp4"]:
            try:
                cluster_id = mly_uploader.upload_blackvue(import_path)
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
            LOG.warning(f"No images found in {desc_path}. Bye.")
            return

        user_items = fetch_user_items(user_name, organization_key)

        # Make sure all descs have uuid assigned
        # It is used to find the right sequence when writing upload history
        missing_sequence_uuid = str(uuid.uuid4())
        for desc in descs:
            if "MAPSequenceUUID" not in desc:
                desc["MAPSequenceUUID"] = missing_sequence_uuid

        if not dry_run:
            _setup_write_upload_history(emitter, params, descs)

        mly_uploader = uploader.Uploader(user_items, emitter=emitter, dry_run=dry_run)
        try:
            mly_uploader.upload_images(_join_desc_path(import_path, descs))
        except Exception as exc:
            if not dry_run:
                _api_logging_failed(user_items, _summarize(stats), exc)
            raise
    else:
        raise RuntimeError(f"Expect {import_path} to be either file or directory")

    # if there is something uploaded
    if stats:
        upload_summary = _summarize(stats)

        LOG.info(
            "Upload summary (in megabytes/second): %s",
            json.dumps(upload_summary, indent=4),
        )
        if not dry_run:
            _api_logging_finished(user_items, upload_summary)
    else:
        LOG.info("Nothing uploaded. Bye.")
