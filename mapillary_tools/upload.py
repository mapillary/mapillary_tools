from __future__ import annotations

import json
import logging
import os
import sys
import time
import typing as T
import uuid
from pathlib import Path

import requests
from tqdm import tqdm

from . import (
    api_v4,
    constants,
    exceptions,
    geo,
    history,
    ipc,
    telemetry,
    types,
    upload_api_v4,
    uploader,
    utils,
    VERSION,
)
from .camm import camm_builder, camm_parser
from .gpmf import gpmf_parser
from .mp4 import simple_mp4_builder
from .types import FileType

JSONDict = T.Dict[str, T.Union[str, int, float, None]]

LOG = logging.getLogger(__name__)


class UploadError(Exception):
    def __init__(self, inner_ex) -> None:
        self.inner_ex = inner_ex
        super().__init__(str(inner_ex))


def _load_validate_metadatas_from_desc_path(
    desc_path: str | None, import_paths: T.Sequence[Path]
) -> list[types.Metadata]:
    is_default_desc_path = False
    if desc_path is None:
        is_default_desc_path = True
        if len(import_paths) == 1 and import_paths[0].is_dir():
            desc_path = str(
                import_paths[0].joinpath(constants.IMAGE_DESCRIPTION_FILENAME)
            )
        else:
            if 1 < len(import_paths):
                raise exceptions.MapillaryBadParameterError(
                    "The description path must be specified (with --desc_path) when uploading multiple paths",
                )
            else:
                raise exceptions.MapillaryBadParameterError(
                    "The description path must be specified (with --desc_path) when uploading a single file",
                )

    descs: list[types.DescriptionOrError] = []

    if desc_path == "-":
        try:
            descs = json.load(sys.stdin)
        except json.JSONDecodeError as ex:
            raise exceptions.MapillaryInvalidDescriptionFile(
                f"Invalid JSON stream from stdin: {ex}"
            )
    else:
        if not os.path.isfile(desc_path):
            if is_default_desc_path:
                raise exceptions.MapillaryFileNotFoundError(
                    f"Description file {desc_path} not found. Has the directory been processed yet?"
                )
            else:
                raise exceptions.MapillaryFileNotFoundError(
                    f"Description file {desc_path} not found"
                )
        with open(desc_path) as fp:
            try:
                descs = json.load(fp)
            except json.JSONDecodeError as ex:
                raise exceptions.MapillaryInvalidDescriptionFile(
                    f"Invalid JSON file {desc_path}: {ex}"
                )

    # the descs load from stdin or json file may contain invalid entries
    validated_descs = [
        types.validate_and_fail_desc(desc)
        for desc in descs
        # skip error descriptions
        if "error" not in desc
    ]

    # throw if we found any invalid descs
    invalid_descs = [desc for desc in validated_descs if "error" in desc]
    if invalid_descs:
        for desc in invalid_descs:
            LOG.error("Invalid description entry: %s", json.dumps(desc))
        raise exceptions.MapillaryInvalidDescriptionFile(
            f"Found {len(invalid_descs)} invalid descriptions"
        )

    # validated_descs should contain no errors
    return [
        types.from_desc(T.cast(types.Description, desc)) for desc in validated_descs
    ]


def zip_images(
    import_path: Path,
    zip_dir: Path,
    desc_path: str | None = None,
):
    if not import_path.is_dir():
        raise exceptions.MapillaryFileNotFoundError(
            f"Import directory not found: {import_path}"
        )

    metadatas = _load_validate_metadatas_from_desc_path(desc_path, [import_path])

    if not metadatas:
        LOG.warning("No images or videos found in %s", desc_path)
        return

    image_metadatas = [
        metadata for metadata in metadatas if isinstance(metadata, types.ImageMetadata)
    ]

    uploader.ZipImageSequence.zip_images(image_metadatas, zip_dir)


def _setup_cancel_due_to_duplication(emitter: uploader.EventEmitter) -> None:
    @emitter.on("upload_start")
    def upload_start(payload: uploader.Progress):
        md5sum = payload["md5sum"]
        if history.is_uploaded(md5sum):
            sequence_uuid = payload.get("sequence_uuid")
            if sequence_uuid is None:
                basename = os.path.basename(payload.get("import_path", ""))
                LOG.info(
                    "File %s has been uploaded already. Check the upload history at %s",
                    basename,
                    history.history_desc_path(md5sum),
                )
            else:
                LOG.info(
                    "Sequence %s has been uploaded already. Check the upload history at %s",
                    sequence_uuid,
                    history.history_desc_path(md5sum),
                )
            raise uploader.UploadCancelled()


def _setup_write_upload_history(
    emitter: uploader.EventEmitter,
    params: JSONDict,
    metadatas: list[types.Metadata] | None = None,
) -> None:
    @emitter.on("upload_finished")
    def upload_finished(payload: uploader.Progress):
        sequence_uuid = payload.get("sequence_uuid")
        md5sum = payload["md5sum"]
        if sequence_uuid is None or metadatas is None:
            sequence = None
        else:
            sequence = [
                metadata
                for metadata in metadatas
                if isinstance(metadata, types.ImageMetadata)
                and metadata.MAPSequenceUUID == sequence_uuid
            ]
            sequence.sort(key=lambda metadata: metadata.sort_key())
        try:
            history.write_history(
                md5sum,
                params,
                T.cast(JSONDict, payload),
                sequence,
            )
        except OSError:
            LOG.warning("Error writing upload history %s", md5sum, exc_info=True)


def _setup_tdqm(emitter: uploader.EventEmitter) -> None:
    upload_pbar: tqdm | None = None

    @emitter.on("upload_fetch_offset")
    def upload_fetch_offset(payload: uploader.Progress) -> None:
        nonlocal upload_pbar

        if upload_pbar is not None:
            upload_pbar.close()

        nth = payload["sequence_idx"] + 1
        total = payload["total_sequence_count"]
        import_path: str | None = payload.get("import_path")
        filetype = payload.get("file_type", "unknown").upper()
        if import_path is None:
            _desc = f"Uploading {filetype} ({nth}/{total})"
        else:
            _desc = (
                f"Uploading {filetype} {os.path.basename(import_path)} ({nth}/{total})"
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
        LOG.debug("IPC %s: %s", type.upper(), payload)
        ipc.send(type, payload)

    @emitter.on("upload_fetch_offset")
    def upload_fetch_offset(payload: uploader.Progress) -> None:
        type: uploader.EventName = "upload_fetch_offset"
        LOG.debug("IPC %s: %s", type.upper(), payload)
        ipc.send(type, payload)

    @emitter.on("upload_progress")
    def upload_progress(payload: uploader.Progress):
        type: uploader.EventName = "upload_progress"

        if LOG.getEffectiveLevel() <= logging.DEBUG:
            # In debug mode, we want to see the progress every 10 seconds
            # instead of every chunk (which is too verbose)
            INTERVAL_SECONDS = 10
            now = time.time()
            last_upload_progress_debug_at: float | None = T.cast(T.Dict, payload).get(
                "_last_upload_progress_debug_at"
            )
            if (
                last_upload_progress_debug_at is None
                or last_upload_progress_debug_at + INTERVAL_SECONDS < now
            ):
                LOG.debug("IPC %s: %s", type.upper(), payload)
                T.cast(T.Dict, payload)["_last_upload_progress_debug_at"] = now

        ipc.send(type, payload)

    @emitter.on("upload_end")
    def upload_end(payload: uploader.Progress) -> None:
        type: uploader.EventName = "upload_end"
        LOG.debug("IPC %s: %s", type.upper(), payload)
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
    all_stats: list[_APIStats] = []

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

    @emitter.on("upload_finished")
    def append_stats(payload: _APIStats) -> None:
        all_stats.append(payload)

    return all_stats


def _summarize(stats: T.Sequence[_APIStats]) -> dict:
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
    grouped: dict[str, list[_APIStats]] = {}
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


def _api_logging_finished(summary: dict):
    if constants.MAPILLARY_DISABLE_API_LOGGING:
        return

    action: api_v4.ActionType = "upload_finished_upload"
    LOG.debug("API Logging for action %s: %s", action, summary)
    try:
        api_v4.log_event(action, summary)
    except requests.HTTPError as exc:
        LOG.warning(
            "HTTPError from API Logging for action %s: %s",
            action,
            api_v4.readable_http_error(exc),
        )
    except Exception:
        LOG.warning("Error from API Logging for action %s", action, exc_info=True)


def _api_logging_failed(payload: dict, exc: Exception):
    if constants.MAPILLARY_DISABLE_API_LOGGING:
        return

    payload_with_reason = {**payload, "reason": exc.__class__.__name__}
    action: api_v4.ActionType = "upload_failed_upload"
    LOG.debug("API Logging for action %s: %s", action, payload)
    try:
        api_v4.log_event(action, payload_with_reason)
    except requests.HTTPError as exc:
        LOG.warning(
            "HTTPError from API Logging for action %s: %s",
            action,
            api_v4.readable_http_error(exc),
        )
    except Exception:
        LOG.warning("Error from API Logging for action %s", action, exc_info=True)


def _load_descs(
    _metadatas_from_process: T.Sequence[types.MetadataOrError] | None,
    desc_path: str | None,
    import_paths: T.Sequence[Path],
) -> list[types.Metadata]:
    metadatas: list[types.Metadata]

    if _metadatas_from_process is not None:
        metadatas = [
            metadata
            for metadata in _metadatas_from_process
            if not isinstance(metadata, types.ErrorMetadata)
        ]
    else:
        metadatas = _load_validate_metadatas_from_desc_path(desc_path, import_paths)

    # Make sure all metadatas have sequence uuid assigned
    # It is used to find the right sequence when writing upload history
    missing_sequence_uuid = str(uuid.uuid4())
    for metadata in metadatas:
        if isinstance(metadata, types.ImageMetadata):
            if metadata.MAPSequenceUUID is None:
                metadata.MAPSequenceUUID = missing_sequence_uuid

    for metadata in metadatas:
        assert isinstance(metadata, (types.ImageMetadata, types.VideoMetadata))
        if isinstance(metadata, types.ImageMetadata):
            assert metadata.MAPSequenceUUID is not None

    return metadatas


_M = T.TypeVar("_M", bound=types.Metadata)


def _find_metadata_with_filename_existed_in(
    metadatas: T.Sequence[_M], paths: T.Sequence[Path]
) -> list[_M]:
    resolved_image_paths = set(p.resolve() for p in paths)
    return [d for d in metadatas if d.filename.resolve() in resolved_image_paths]


def _upload_everything(
    mly_uploader: uploader.Uploader,
    metadatas: T.Sequence[types.Metadata],
    import_paths: T.Sequence[Path],
    skip_subfolders: bool,
):
    # Upload images
    image_paths = utils.find_images(import_paths, skip_subfolders=skip_subfolders)
    # Find descs that match the image paths from the import paths
    image_metadatas = [
        metadata
        for metadata in (metadatas or [])
        if isinstance(metadata, types.ImageMetadata)
    ]
    specified_image_metadatas = _find_metadata_with_filename_existed_in(
        image_metadatas, image_paths
    )
    if specified_image_metadatas:
        try:
            clusters = uploader.ZipImageSequence.prepare_images_and_upload(
                specified_image_metadatas,
                mly_uploader,
            )
        except Exception as ex:
            raise UploadError(ex) from ex

        if clusters:
            LOG.debug("Uploaded to cluster: %s", clusters)

    # Upload videos
    video_paths = utils.find_videos(import_paths, skip_subfolders=skip_subfolders)
    video_metadatas = [
        metadata
        for metadata in (metadatas or [])
        if isinstance(metadata, types.VideoMetadata)
    ]
    specified_video_metadatas = _find_metadata_with_filename_existed_in(
        video_metadatas, video_paths
    )
    _upload_videos(mly_uploader, specified_video_metadatas)

    # Upload zip files
    zip_paths = utils.find_zipfiles(import_paths, skip_subfolders=skip_subfolders)
    _upload_zipfiles(mly_uploader, zip_paths)


def _upload_videos(
    mly_uploader: uploader.Uploader, video_metadatas: T.Sequence[types.VideoMetadata]
):
    for idx, video_metadata in enumerate(video_metadatas):
        video_metadata.update_md5sum()
        assert isinstance(video_metadata.md5sum, str), "md5sum should be updated"

        camm_info = _prepare_camm_info(video_metadata)

        generator = camm_builder.camm_sample_generator2(camm_info)

        with video_metadata.filename.open("rb") as src_fp:
            camm_fp = simple_mp4_builder.transform_mp4(src_fp, generator)
            progress: uploader.SequenceProgress = {
                "total_sequence_count": len(video_metadatas),
                "sequence_idx": idx,
                "file_type": video_metadata.filetype.value,
                "import_path": str(video_metadata.filename),
                "md5sum": video_metadata.md5sum,
            }

            session_key = uploader._session_key(
                video_metadata.md5sum, upload_api_v4.ClusterFileType.CAMM
            )

            try:
                cluster_id = mly_uploader.upload_stream(
                    T.cast(T.BinaryIO, camm_fp),
                    upload_api_v4.ClusterFileType.CAMM,
                    session_key,
                    progress=T.cast(T.Dict[str, T.Any], progress),
                )
            except Exception as ex:
                raise UploadError(ex) from ex
            LOG.debug("Uploaded to cluster: %s", cluster_id)


def _prepare_camm_info(video_metadata: types.VideoMetadata) -> camm_parser.CAMMInfo:
    camm_info = camm_parser.CAMMInfo(
        make=video_metadata.make or "", model=video_metadata.model or ""
    )

    for point in video_metadata.points:
        if isinstance(point, telemetry.CAMMGPSPoint):
            if camm_info.gps is None:
                camm_info.gps = []
            camm_info.gps.append(point)

        elif isinstance(point, telemetry.GPSPoint):
            # There is no proper CAMM entry for GoPro GPS
            if camm_info.mini_gps is None:
                camm_info.mini_gps = []
            camm_info.mini_gps.append(point)

        elif isinstance(point, geo.Point):
            if camm_info.mini_gps is None:
                camm_info.mini_gps = []
            camm_info.mini_gps.append(point)
        else:
            raise ValueError(f"Unknown point type: {point}")

    if constants.MAPILLARY__EXPERIMENTAL_ENABLE_IMU:
        if video_metadata.filetype is FileType.GOPRO:
            with video_metadata.filename.open("rb") as fp:
                gopro_info = gpmf_parser.extract_gopro_info(fp, telemetry_only=True)
            if gopro_info is not None:
                camm_info.accl = gopro_info.accl or []
                camm_info.gyro = gopro_info.gyro or []
                camm_info.magn = gopro_info.magn or []

    return camm_info


def _normalize_import_paths(import_path: Path | T.Sequence[Path]) -> list[Path]:
    import_paths: list[Path]

    if isinstance(import_path, Path):
        import_paths = [import_path]
    else:
        assert isinstance(import_path, list)
        import_paths = import_path

    import_paths = list(utils.deduplicate_paths(import_paths))

    # Check and fail early
    for path in import_paths:
        if not path.is_file() and not path.is_dir():
            raise exceptions.MapillaryFileNotFoundError(
                f"Import file or directory not found: {path}"
            )

    return import_paths


def upload(
    import_path: Path | T.Sequence[Path],
    user_items: types.UserItem,
    desc_path: str | None = None,
    _metadatas_from_process: T.Sequence[types.MetadataOrError] | None = None,
    dry_run=False,
    skip_subfolders=False,
) -> None:
    import_paths = _normalize_import_paths(import_path)

    metadatas = _load_descs(_metadatas_from_process, desc_path, import_paths)

    # Setup the emitter -- the order matters here

    emitter = uploader.EventEmitter()

    # When dry_run mode is on, we disable history by default.
    # But we need dry_run for tests, so we added MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN
    # and when it is on, we enable history regardless of dry_run
    enable_history = constants.MAPILLARY_UPLOAD_HISTORY_PATH and (
        not dry_run or constants.MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN
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
        # null if multiple paths provided
        "import_path": str(import_path) if isinstance(import_path, Path) else None,
        "organization_key": user_items.get("MAPOrganizationKey"),
        "user_key": user_items.get("MAPSettingsUserKey"),
        "version": VERSION,
    }

    if enable_history:
        _setup_write_upload_history(emitter, params, metadatas)

    mly_uploader = uploader.Uploader(user_items, emitter=emitter, dry_run=dry_run)

    try:
        _upload_everything(mly_uploader, metadatas, import_paths, skip_subfolders)
    except UploadError as ex:
        inner_ex = ex.inner_ex

        if not dry_run:
            _api_logging_failed(_summarize(stats), inner_ex)

        if isinstance(inner_ex, requests.ConnectionError):
            raise exceptions.MapillaryUploadConnectionError(str(inner_ex)) from inner_ex

        if isinstance(inner_ex, requests.Timeout):
            raise exceptions.MapillaryUploadTimeoutError(str(inner_ex)) from inner_ex

        if isinstance(inner_ex, requests.HTTPError) and isinstance(
            inner_ex.response, requests.Response
        ):
            if api_v4.is_auth_error(inner_ex.response):
                raise exceptions.MapillaryUploadUnauthorizedError(
                    api_v4.extract_auth_error_message(inner_ex.response)
                ) from inner_ex
            raise inner_ex

        raise inner_ex

    if stats:
        if not dry_run:
            _api_logging_finished(_summarize(stats))
        _show_upload_summary(stats)
    else:
        LOG.info("Nothing uploaded. Bye.")


def _upload_zipfiles(
    mly_uploader: uploader.Uploader,
    zip_paths: T.Sequence[Path],
) -> None:
    for idx, zip_path in enumerate(zip_paths):
        progress: uploader.SequenceProgress = {
            "total_sequence_count": len(zip_paths),
            "sequence_idx": idx,
            "import_path": str(zip_path),
        }
        try:
            cluster_id = uploader.ZipImageSequence.prepare_zipfile_and_upload(
                zip_path, mly_uploader, progress=T.cast(T.Dict[str, T.Any], progress)
            )
        except Exception as ex:
            raise UploadError(ex) from ex

        LOG.debug("Uploaded to cluster: %s", cluster_id)
