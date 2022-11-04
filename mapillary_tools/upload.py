import json
import logging
import os
import string
import sys
import time
import typing as T
import uuid
from pathlib import Path

if sys.version_info >= (3, 8):
    from typing import Literal  # pylint: disable=no-name-in-module
else:
    from typing_extensions import Literal

import requests
from tqdm import tqdm

from . import (
    api_v4,
    authenticate,
    config,
    constants,
    exceptions,
    geo,
    ipc,
    types,
    uploader,
    utils,
)
from .geotag import (
    blackvue_parser,
    camm_builder,
    camm_parser,
    gpmf_gps_filter,
    gpmf_parser,
    simple_mp4_builder,
    utils as video_utils,
)
from .utils import FileType

JSONDict = T.Dict[str, T.Union[str, int, float, None]]

LOG = logging.getLogger(__name__)
MAPILLARY_DISABLE_API_LOGGING = os.getenv("MAPILLARY_DISABLE_API_LOGGING")
MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN = os.getenv(
    "MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN"
)
# Disable if it's set to empty
MAPILLARY_UPLOAD_HISTORY_PATH = os.getenv(
    "MAPILLARY_UPLOAD_HISTORY_PATH",
    os.path.join(
        constants.USER_DATA_DIR,
        "upload_history",
    ),
)
CAMM_CONVERTABLES = {FileType.CAMM, FileType.BLACKVUE, FileType.GOPRO}


class UploadError(Exception):
    def __init__(self, inner_ex) -> None:
        self.inner_ex = inner_ex
        super().__init__(str(inner_ex))


class UploadHTTPError(Exception):
    pass


def wrap_http_exception(ex: requests.HTTPError):
    resp = ex.response
    lines = [
        f"{ex.request.method} {resp.url}",
        f"> HTTP Status: {ex.response.status_code}",
        f"{resp.content}",
    ]
    return UploadHTTPError("\n".join(lines))


def read_image_descriptions(desc_path: str) -> T.List[types.ImageDescriptionFile]:
    descs: T.List[types.ImageDescriptionFile] = []

    if desc_path == "-":
        try:
            descs = json.load(sys.stdin)
        except json.JSONDecodeError as ex:
            raise exceptions.MapillaryInvalidDescriptionFile(
                f"Invalid JSON stream from stdin: {ex}"
            )
    else:
        if not os.path.isfile(desc_path):
            raise exceptions.MapillaryFileNotFoundError(
                f"Image description file {desc_path} not found. Please process the image directory first"
            )
        with open(desc_path) as fp:
            try:
                descs = json.load(fp)
            except json.JSONDecodeError as ex:
                raise exceptions.MapillaryInvalidDescriptionFile(
                    f"Invalid JSON file {desc_path}: {ex}"
                )

    return types.filter_out_errors(
        T.cast(T.List[types.ImageDescriptionFileOrError], descs)
    )


def zip_images(
    import_path: Path,
    zip_dir: Path,
    desc_path: T.Optional[str] = None,
):
    if not import_path.is_dir():
        raise exceptions.MapillaryFileNotFoundError(
            f"Import directory not found: {import_path}"
        )

    if desc_path is None:
        desc_path = str(import_path.joinpath(constants.IMAGE_DESCRIPTION_FILENAME))

    descs = read_image_descriptions(desc_path)

    if not descs:
        LOG.warning("No images found in %s", desc_path)
        return

    uploader.zip_images(descs, zip_dir)


def fetch_user_items(
    user_name: T.Optional[str] = None, organization_key: T.Optional[str] = None
) -> types.UserItem:
    if user_name is None:
        all_user_items = config.list_all_users()
        if not all_user_items:
            raise exceptions.MapillaryBadParameterError(
                "No Mapillary account found. Add one with --user_name"
            )
        if len(all_user_items) == 1:
            user_items = all_user_items[0]
        else:
            raise exceptions.MapillaryBadParameterError(
                f"Found multiple Mapillary accounts. Please specify one with --user_name"
            )
    else:
        try:
            user_items = authenticate.authenticate_user(user_name)
        except requests.HTTPError as exc:
            raise wrap_http_exception(exc) from exc

    if organization_key is not None:
        try:
            resp = api_v4.fetch_organization(
                user_items["user_upload_token"], organization_key
            )
        except requests.HTTPError as ex:
            raise wrap_http_exception(ex) from ex
        org = resp.json()
        LOG.info("Uploading to organization: %s", json.dumps(org))
        user_items = T.cast(
            types.UserItem, {**user_items, "MAPOrganizationKey": organization_key}
        )
    return user_items


def _validate_hexdigits(md5sum: str):
    try:
        assert set(md5sum).issubset(string.hexdigits)
        assert 4 <= len(md5sum)
        _ = int(md5sum, 16)
    except Exception:
        raise ValueError(f"Invalid md5sum {md5sum}")


def _history_desc_path(md5sum: str) -> Path:
    assert MAPILLARY_UPLOAD_HISTORY_PATH is not None
    _validate_hexdigits(md5sum)
    subfolder = md5sum[:2]
    assert subfolder, f"Invalid md5sum {md5sum}"
    basename = md5sum[2:]
    assert basename, f"Invalid md5sum {md5sum}"
    return (
        Path(MAPILLARY_UPLOAD_HISTORY_PATH)
        .joinpath(subfolder)
        .joinpath(f"{basename}.json")
    )


def is_uploaded(md5sum: str) -> bool:
    if not MAPILLARY_UPLOAD_HISTORY_PATH:
        return False
    return _history_desc_path(md5sum).is_file()


def write_history(
    md5sum: str,
    params: JSONDict,
    summary: JSONDict,
    descs: T.Optional[T.List[types.ImageDescriptionFile]] = None,
) -> None:
    if not MAPILLARY_UPLOAD_HISTORY_PATH:
        return
    path = _history_desc_path(md5sum)
    LOG.debug("Writing upload history: %s", path)
    path.resolve().parent.mkdir(parents=True, exist_ok=True)
    history: T.Dict[str, T.Any] = {
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
                    "File %s has been uploaded already. Check the upload history at %s",
                    basename,
                    _history_desc_path(md5sum),
                )
            else:
                LOG.info(
                    "Sequence %s has been uploaded already. Check the upload history at %s",
                    sequence_uuid,
                    _history_desc_path(md5sum),
                )
            raise uploader.UploadCancelled()


def _setup_write_upload_history(
    emitter: uploader.EventEmitter,
    params: JSONDict,
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
                T.cast(JSONDict, payload),
                sequence,
            )
        except OSError:
            LOG.warning("Error writing upload history %s", md5sum, exc_info=True)


def _setup_tdqm(emitter: uploader.EventEmitter) -> None:
    upload_pbar: T.Optional[tqdm] = None

    @emitter.on("upload_fetch_offset")
    def upload_fetch_offset(payload: uploader.Progress) -> None:
        nonlocal upload_pbar

        if upload_pbar is not None:
            upload_pbar.close()

        nth = payload["sequence_idx"] + 1
        total = payload["total_sequence_count"]
        import_path: T.Optional[str] = payload.get("import_path")
        file_type = payload.get("file_type", "unknown").upper()
        if import_path is None:
            _desc = f"Uploading {file_type} ({nth}/{total})"
        else:
            _desc = (
                f"Uploading {file_type} {os.path.basename(import_path)} ({nth}/{total})"
            )
        upload_pbar = tqdm(
            total=payload["entity_size"],
            desc=_desc,
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
    def upload_end(_: uploader.Progress) -> None:
        nonlocal upload_pbar
        if upload_pbar:
            upload_pbar.close()
        upload_pbar = None


def _setup_ipc(emitter: uploader.EventEmitter):
    @emitter.on("upload_start")
    def upload_start(payload: uploader.Progress):
        type: uploader.EventName = "upload_start"
        LOG.debug("Sending %s via IPC: %s", type, payload)
        ipc.send(type, payload)

    @emitter.on("upload_fetch_offset")
    def upload_fetch_offset(payload: uploader.Progress) -> None:
        type: uploader.EventName = "upload_fetch_offset"
        LOG.debug("Sending %s via IPC: %s", type, payload)
        ipc.send(type, payload)

    @emitter.on("upload_progress")
    def upload_progress(payload: uploader.Progress):
        type: uploader.EventName = "upload_progress"
        LOG.debug("Sending %s via IPC: %s", type, payload)
        ipc.send(type, payload)

    @emitter.on("upload_end")
    def upload_end(payload: uploader.Progress) -> None:
        type: uploader.EventName = "upload_end"
        LOG.debug("Sending %s via IPC: %s", type, payload)
        ipc.send(type, payload)


class _APIStats(uploader.Progress, total=False):
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
        # could be None if it failed to fetch offset
        restart_time = payload.get("upload_last_restart_time")
        if restart_time is not None:
            payload["upload_total_time"] += time.time() - restart_time
            # reset the restart time
            del payload["upload_last_restart_time"]

    @emitter.on("upload_end")
    def collect_end_time(payload: _APIStats) -> None:
        now = time.time()
        payload["upload_end_time"] = now
        payload["upload_total_time"] += now - payload["upload_last_restart_time"]
        all_stats.append(payload)

    return all_stats


def _summarize(stats: T.Sequence[_APIStats]) -> T.Dict:
    total_image_count = sum(s.get("sequence_image_count", 0) for s in stats)
    total_uploaded_sequence_count = len(stats)
    # note that stats[0]["total_sequence_count"] not always same as total_uploaded_sequence_count

    total_uploaded_size = sum(
        s["entity_size"] - s.get("upload_first_offset", 0) for s in stats
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


def _show_upload_summary(stats: T.Sequence[_APIStats]):
    grouped: T.Dict[str, T.List[_APIStats]] = {}
    for stat in stats:
        grouped.setdefault(stat.get("file_type", "unknown"), []).append(stat)

    for file_type, typed_stats in grouped.items():
        if file_type == FileType.IMAGE.value:
            LOG.info(
                "%8d  %s sequences uploaded",
                len(typed_stats),
                file_type.upper(),
            )
        else:
            LOG.info(
                "%8d  %s files uploaded",
                len(typed_stats),
                file_type.upper(),
            )

    summary = _summarize(stats)
    LOG.info("%8.1fM data in total", summary["size"])
    LOG.info("%8.1fM data uploaded", summary["uploaded_size"])
    LOG.info("%8.1fs upload time", summary["time"])


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
            exc_info=wrap_http_exception(exc),
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
        wrapped_exc = wrap_http_exception(exc)
        LOG.warning(
            "Error from API Logging for action %s",
            action,
            exc_info=wrapped_exc,
        )
    except:
        LOG.warning("Error from API Logging for action %s", action, exc_info=True)


def _load_descs_for_images(
    _descs_from_process: T.Optional[T.Sequence[types.ImageDescriptionFileOrError]],
    desc_path: T.Optional[str],
    import_paths: T.Sequence[Path],
) -> T.List[types.ImageDescriptionFile]:
    if _descs_from_process is not None:
        new_descs = types.filter_out_errors(_descs_from_process)
    else:
        if desc_path is None:
            if len(import_paths) == 1 and import_paths[0].is_dir():
                desc_path = str(
                    import_paths[0].joinpath(constants.IMAGE_DESCRIPTION_FILENAME)
                )
            else:
                if 1 < len(import_paths):
                    raise exceptions.MapillaryBadParameterError(
                        "desc_path is required if multiple import paths are specified"
                    )
                else:
                    raise exceptions.MapillaryBadParameterError(
                        "desc_path is required if the import path is not a directory"
                    )

        new_descs = read_image_descriptions(desc_path)

    # Make sure all descs have uuid assigned
    # It is used to find the right sequence when writing upload history
    missing_sequence_uuid = str(uuid.uuid4())
    for desc in new_descs:
        if "MAPSequenceUUID" not in desc:
            desc["MAPSequenceUUID"] = missing_sequence_uuid

    return new_descs


def upload(
    import_path: T.Union[Path, T.Sequence[Path]],
    file_types: T.Set[FileType],
    desc_path: T.Optional[str] = None,
    _descs_from_process: T.Optional[
        T.Sequence[types.ImageDescriptionFileOrError]
    ] = None,
    user_name: T.Optional[str] = None,
    organization_key: T.Optional[str] = None,
    dry_run=False,
    skip_subfolders=False,
) -> None:
    if FileType.RAW_BLACKVUE in file_types and FileType.BLACKVUE in file_types:
        raise exceptions.MapillaryBadParameterError(
            f"file_types should contain either {FileType.RAW_BLACKVUE.value} or {FileType.BLACKVUE.value}, not both",
        )

    if FileType.RAW_CAMM in file_types and FileType.CAMM in file_types:
        raise exceptions.MapillaryBadParameterError(
            f"File types should contain either {FileType.RAW_CAMM.value} or {FileType.CAMM.value}, not both",
        )
    file_types = set(file_types)

    import_paths: T.Sequence[Path]
    if isinstance(import_path, Path):
        import_paths = [import_path]
    else:
        assert isinstance(import_path, list)
        import_paths = import_path
    import_paths = list(utils.deduplicate_paths(import_paths))

    if not import_paths:
        return

    # Check and fail early
    for path in import_paths:
        if not path.is_file() and not path.is_dir():
            raise exceptions.MapillaryFileNotFoundError(
                f"Import file or directory not found: {path}"
            )

    if FileType.IMAGE in file_types:
        descs = _load_descs_for_images(_descs_from_process, desc_path, import_paths)
    else:
        descs = None

    user_items = fetch_user_items(user_name, organization_key)

    # Setup the emitter -- the order matters here

    emitter = uploader.EventEmitter()

    enable_history = MAPILLARY_UPLOAD_HISTORY_PATH and (
        not dry_run or MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN == "YES"
    )

    # Put it first one to cancel early
    if enable_history:
        _setup_cancel_due_to_duplication(emitter)

    # This one set up tdqm
    _setup_tdqm(emitter)

    # Now stats is empty but it will collect during upload
    stats = _setup_api_stats(emitter)

    # Send the progress as well as the log stats collected above
    _setup_ipc(emitter)

    params: JSONDict = {
        "import_path": str(import_path),
        "desc_path": desc_path,
        "user_key": user_items.get("MAPSettingsUserKey"),
        "organization_key": user_items.get("MAPOrganizationKey"),
    }

    if enable_history:
        _setup_write_upload_history(emitter, params, descs)

    mly_uploader = uploader.Uploader(
        user_items,
        emitter=emitter,
        dry_run=dry_run,
        chunk_size=int(constants.UPLOAD_CHUNK_SIZE_MB * 1024 * 1024),
    )

    image_paths = utils.find_images(import_paths, skip_subfolders=skip_subfolders)
    video_paths = utils.find_videos(import_paths, skip_subfolders=skip_subfolders)
    zip_paths = utils.find_zipfiles(import_paths, skip_subfolders=skip_subfolders)

    try:
        if FileType.IMAGE in file_types:
            # find descs that match the image paths from the import paths
            resolved_image_paths = set(p.resolve() for p in image_paths)
            specified_descs = [
                d
                for d in (descs or [])
                if Path(d["filename"]).resolve() in resolved_image_paths
            ]
            clusters = mly_uploader.upload_images(
                specified_descs, event_payload={"file_type": FileType.IMAGE.value}
            )
            LOG.debug(f"Uploaded to cluster: %s", clusters)

        supported = CAMM_CONVERTABLES.intersection(file_types)
        if supported:
            _convert_and_upload_camm(mly_uploader, video_paths, supported)

        if FileType.RAW_BLACKVUE in file_types:
            _upload_raw_blackvues(mly_uploader, video_paths)

        if FileType.RAW_CAMM in file_types:
            _upload_raw_camm(mly_uploader, video_paths)

        if FileType.ZIP in file_types:
            _upload_zipfiles(mly_uploader, zip_paths)

    except UploadError as ex:
        if not dry_run:
            _api_logging_failed(mly_uploader.user_items, _summarize(stats), ex.inner_ex)
        if isinstance(ex.inner_ex, requests.HTTPError):
            raise wrap_http_exception(ex.inner_ex) from ex.inner_ex
        else:
            raise ex

    if stats:
        if not dry_run:
            _api_logging_finished(user_items, _summarize(stats))
        _show_upload_summary(stats)
    else:
        LOG.info("Nothing uploaded. Bye.")


def _convert_and_upload_camm(
    mly_uploader: uploader.Uploader,
    video_paths: T.Sequence[Path],
    file_types: T.Set[FileType],
) -> None:
    for idx, video_path in enumerate(video_paths):
        LOG.debug("Converting and uploading %s", video_path)
        with open(video_path, "rb") as src_fp:
            metadata = camm_builder.extract_video_metadata(src_fp, file_types)
            if metadata is None:
                LOG.warning(
                    f"Skipping %s due to: No GPS found in the video",
                    video_path.name,
                )
                continue

            if metadata.file_type == FileType.GOPRO:
                metadata.points = T.cast(
                    T.List[geo.Point],
                    gpmf_gps_filter.filter_noisy_points(
                        T.cast(T.List[gpmf_parser.PointWithFix], metadata.points)
                    ),
                )

            stationary = video_utils.is_video_stationary(
                geo.get_max_distance_from_start(
                    [(p.lat, p.lon) for p in metadata.points]
                )
            )
            if stationary:
                LOG.warning(
                    f"Skipping %s %s due to: Stationary video",
                    metadata.file_type.value.upper(),
                    video_path.name,
                )
                continue

            generator = camm_builder.camm_sample_generator2(metadata)
            camm_fp = simple_mp4_builder.transform_mp4(src_fp, generator)
            event_payload: uploader.Progress = {
                "total_sequence_count": len(video_paths),
                "sequence_idx": idx,
                "file_type": metadata.file_type.value,
                "import_path": str(video_path),
            }
            try:
                cluster_id = mly_uploader.upload_camm_fp(
                    T.cast(T.BinaryIO, camm_fp), event_payload=event_payload
                )
            except Exception as ex:
                raise UploadError(ex) from ex

        LOG.debug(f"Uploaded to cluster: %s", cluster_id)


def _check_blackvue(video_path: Path) -> None:
    # Skip in tests only because we don't have valid sample blackvue for tests
    if os.getenv("MAPILLARY__DISABLE_BLACKVUE_CHECK") == "YES":
        return

    points = blackvue_parser.parse_gps_points(video_path)
    if not points:
        raise exceptions.MapillaryGPXEmptyError(f"No GPS found in the BlackVue video")

    stationary = video_utils.is_video_stationary(
        geo.get_max_distance_from_start([(p.lat, p.lon) for p in points])
    )
    if stationary:
        raise exceptions.MapillaryStationaryVideoError(f"Stationary BlackVue video")


def _upload_raw_blackvues(
    mly_uploader: uploader.Uploader,
    video_paths: T.Sequence[Path],
) -> None:
    for idx, video_path in enumerate(video_paths):
        event_payload: uploader.Progress = {
            "total_sequence_count": len(video_paths),
            "sequence_idx": idx,
            "file_type": FileType.RAW_BLACKVUE.value,
            "import_path": str(video_path),
        }

        try:
            _check_blackvue(video_path)
        except Exception as ex:
            LOG.warning(
                f"Skipping %s %s due to: %s",
                FileType.RAW_BLACKVUE.value.upper(),
                video_path.name,
                ex,
            )
            continue

        with video_path.open("rb") as fp:
            try:
                cluster_id = mly_uploader.upload_blackvue_fp(
                    fp, event_payload=event_payload
                )
            except Exception as ex:
                raise UploadError(ex) from ex
        LOG.debug(f"Uploaded to cluster: %s", cluster_id)


def _check_camm(video_path: Path) -> None:
    # Skip in tests only because we don't have valid sample CAMM for tests
    if os.getenv("MAPILLARY__DISABLE_CAMM_CHECK") == "YES":
        return

    points = camm_parser.parse_gpx(video_path)
    if not points:
        raise exceptions.MapillaryGPXEmptyError(f"No GPS found in the CAMM video")

    stationary = video_utils.is_video_stationary(
        geo.get_max_distance_from_start([(p.lat, p.lon) for p in points])
    )
    if stationary:
        raise exceptions.MapillaryStationaryVideoError(f"Stationary CAMM video")


def _upload_raw_camm(
    mly_uploader: uploader.Uploader,
    video_paths: T.Sequence[Path],
) -> None:
    for idx, video_path in enumerate(video_paths):
        event_payload: uploader.Progress = {
            "total_sequence_count": len(video_paths),
            "sequence_idx": idx,
            "file_type": FileType.RAW_CAMM.value,
            "import_path": str(video_path),
        }
        try:
            _check_camm(video_path)
        except Exception as ex:
            LOG.warning(
                f"Skipping %s %s due to: %s",
                FileType.RAW_CAMM.value.upper(),
                video_path.name,
                ex,
            )
            continue
        try:
            with video_path.open("rb") as fp:
                cluster_id = mly_uploader.upload_camm_fp(
                    fp, event_payload=event_payload
                )
        except Exception as ex:
            raise UploadError(ex) from ex

        LOG.debug(f"Uploaded to cluster: %s", cluster_id)


def _upload_zipfiles(
    mly_uploader: uploader.Uploader,
    zip_paths: T.Sequence[Path],
) -> None:
    for idx, zip_path in enumerate(zip_paths):
        event_payload: uploader.Progress = {
            "total_sequence_count": len(zip_paths),
            "sequence_idx": idx,
            "file_type": FileType.ZIP.value,
            "import_path": str(zip_path),
        }
        try:
            cluster_id = mly_uploader.upload_zipfile(
                zip_path, event_payload=event_payload
            )
        except Exception as ex:
            raise UploadError(ex) from ex

        LOG.debug(f"Uploaded to cluster: %s", cluster_id)
