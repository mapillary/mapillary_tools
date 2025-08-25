from __future__ import annotations

import json
import logging
import os
import sys
import time
import typing as T
import uuid
from pathlib import Path

import humanize
import requests
from tqdm import tqdm

from . import (
    api_v4,
    config,
    constants,
    exceptions,
    history,
    http,
    ipc,
    types,
    uploader,
    utils,
    VERSION,
)
from .serializer.description import DescriptionJSONSerializer
from .types import FileType

JSONDict = T.Dict[str, T.Union[str, int, float, None]]

LOG = logging.getLogger(__name__)


class UploadedAlready(uploader.SequenceError):
    pass


def upload(
    import_path: Path | T.Sequence[Path],
    user_items: config.UserItem,
    num_upload_workers: int,
    desc_path: str | None = None,
    _metadatas_from_process: T.Sequence[types.MetadataOrError] | None = None,
    reupload: bool = False,
    dry_run: bool = False,
    nofinish: bool = False,
    noresume: bool = False,
    skip_subfolders: bool = False,
) -> None:
    LOG.info("==> Uploading...")

    import_paths = _normalize_import_paths(import_path)

    metadatas = _load_descs(_metadatas_from_process, import_paths, desc_path)

    config.UserItemSchemaValidator.validate(user_items)

    # Setup the emitter -- the order matters here

    emitter = uploader.EventEmitter()

    # Check duplications first
    if not _is_history_disabled(dry_run):
        upload_run_params: JSONDict = {
            # Null if multiple paths provided
            "import_path": str(import_path) if isinstance(import_path, Path) else None,
            "organization_key": user_items.get("MAPOrganizationKey"),
            "user_key": user_items.get("MAPSettingsUserKey"),
            "version": VERSION,
            "run_at": time.time(),
        }
        _setup_history(
            emitter, upload_run_params, metadatas, reupload=reupload, nofinish=nofinish
        )

    # Set up tdqm
    _setup_tdqm(emitter)

    # Now stats is empty but it will collect during ALL uploads
    stats = _setup_api_stats(emitter)

    # Send the progress via IPC, and log the progress in debug mode
    _setup_ipc(emitter)

    try:
        upload_options = uploader.UploadOptions(
            user_items,
            dry_run=dry_run,
            nofinish=nofinish,
            noresume=noresume,
            num_upload_workers=num_upload_workers,
        )
    except ValueError as ex:
        raise exceptions.MapillaryBadParameterError(str(ex)) from ex

    mly_uploader = uploader.Uploader(upload_options, emitter=emitter)

    results = _gen_upload_everything(
        mly_uploader, metadatas, import_paths, skip_subfolders
    )

    upload_successes = 0
    upload_errors: list[Exception] = []

    # The real uploading happens sequentially here
    try:
        for _, result in results:
            if result.error is not None:
                upload_error = _continue_or_fail(result.error)
                log_exception(upload_error)
                upload_errors.append(upload_error)
            else:
                upload_successes += 1

    except Exception as ex:
        # Fatal error: log and raise
        _api_logging_failed(_summarize(stats), ex, dry_run=dry_run)
        raise ex

    else:
        _api_logging_finished(_summarize(stats), dry_run=dry_run)

    finally:
        # We collected stats after every upload is finished
        assert upload_successes == len(stats), (
            f"Expect {upload_successes} success but got {stats}"
        )
        _show_upload_summary(stats, upload_errors)


def zip_images(import_path: Path, zip_dir: Path, desc_path: str | None = None):
    if not import_path.is_dir():
        raise exceptions.MapillaryFileNotFoundError(
            f"Import directory not found: {import_path}"
        )

    metadatas = _load_valid_metadatas_from_desc_path([import_path], desc_path)

    if not metadatas:
        LOG.warning("No images or videos found in %s", desc_path)
        return

    image_metadatas = [
        metadata for metadata in metadatas if isinstance(metadata, types.ImageMetadata)
    ]

    uploader.ZipUploader.zip_images(image_metadatas, zip_dir)


def log_exception(ex: Exception) -> None:
    if LOG.isEnabledFor(logging.DEBUG):
        exc_info = ex
    else:
        exc_info = None

    exc_name = ex.__class__.__name__

    if isinstance(ex, UploadedAlready):
        LOG.info(f"{exc_name}: {ex}")
    elif isinstance(ex, requests.HTTPError):
        LOG.error(f"{exc_name}: {http.readable_http_error(ex)}", exc_info=exc_info)
    elif isinstance(ex, api_v4.HTTPContentError):
        LOG.error(
            f"{exc_name}: {ex}: {http.readable_http_response(ex.response)}",
            exc_info=exc_info,
        )
    else:
        LOG.error(f"{exc_name}: {ex}", exc_info=exc_info)


def _is_history_disabled(dry_run: bool) -> bool:
    # There is no way to read/write history if the path is not set
    if not constants.MAPILLARY_UPLOAD_HISTORY_PATH:
        return True

    if dry_run:
        # When dry_run mode is on, we disable history by default
        # However, we need dry_run for tests, so we added MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN
        # and when it is on, we enable history regardless of dry_run
        if constants.MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN:
            return False
        else:
            return True

    return False


def _setup_history(
    emitter: uploader.EventEmitter,
    upload_run_params: JSONDict,
    metadatas: list[types.Metadata],
    reupload: bool,
    nofinish: bool,
) -> None:
    @emitter.on("upload_start")
    def check_duplication(payload: uploader.Progress):
        md5sum = payload.get("sequence_md5sum")
        assert md5sum is not None, f"md5sum has to be set for {payload}"

        record = history.read_history_record(md5sum)

        if record is not None:
            history_desc_path = history.history_desc_path(md5sum)
            uploaded_at = record.get("summary", {}).get("upload_end_time", None)

            upload_name = uploader.Uploader._upload_name(payload)

            if reupload:
                if uploaded_at is not None:
                    LOG.info(
                        f"Reuploading {upload_name}, despite being uploaded {humanize.naturaldelta(time.time() - uploaded_at)} ago ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(uploaded_at))})"
                    )
                else:
                    LOG.info(
                        f"Reuploading {upload_name}, despite already being uploaded (see {history_desc_path})"
                    )
            else:
                if uploaded_at is not None:
                    msg = f"Skipping {upload_name}, already uploaded {humanize.naturaldelta(time.time() - uploaded_at)} ago ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(uploaded_at))})"
                else:
                    msg = f"Skipping {upload_name}, already uploaded (see {history_desc_path})"
                raise UploadedAlready(msg)

    @emitter.on("upload_finished")
    def write_history(payload: uploader.Progress):
        if nofinish:
            return

        sequence_uuid = payload.get("sequence_uuid")
        md5sum = payload.get("sequence_md5sum")
        assert md5sum is not None, f"md5sum has to be set for {payload}"

        if sequence_uuid is None:
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
                md5sum, upload_run_params, T.cast(JSONDict, payload), sequence
            )
        except OSError:
            LOG.warning("Error writing upload history %s", md5sum, exc_info=True)


def _setup_tdqm(emitter: uploader.EventEmitter) -> None:
    upload_pbar: tqdm | None = None

    @emitter.on("upload_start")
    def upload_start(payload: uploader.Progress) -> None:
        nonlocal upload_pbar

        if upload_pbar is not None:
            upload_pbar.close()

        nth = payload["sequence_idx"] + 1
        total = payload["total_sequence_count"]
        import_path: str | None = payload.get("import_path")
        filetype = payload.get("file_type", "unknown").upper()
        if import_path is None:
            desc = f"Uploading {filetype} ({nth}/{total})"
        else:
            desc = (
                f"Uploading {filetype} {os.path.basename(import_path)} ({nth}/{total})"
            )
        upload_pbar = tqdm(
            total=payload["entity_size"],
            desc=desc,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            initial=payload.get("offset", 0),
            disable=LOG.isEnabledFor(logging.DEBUG),
        )

    @emitter.on("upload_fetch_offset")
    def upload_fetch_offset(payload: uploader.Progress) -> None:
        assert upload_pbar is not None, (
            "progress_bar must be initialized in upload_start"
        )
        begin_offset = payload.get("begin_offset", 0)
        if begin_offset is not None and begin_offset > 0:
            if upload_pbar.total is not None:
                progress_percent = (begin_offset / upload_pbar.total) * 100
                upload_pbar.write(
                    f"Resuming upload at {begin_offset=} ({progress_percent:3.0f}%)",
                    file=sys.stderr,
                )
            else:
                upload_pbar.write(
                    f"Resuming upload at {begin_offset=}", file=sys.stderr
                )
            upload_pbar.reset()
            upload_pbar.update(begin_offset)
            upload_pbar.refresh()

    @emitter.on("upload_progress")
    def upload_progress(payload: uploader.Progress) -> None:
        assert upload_pbar is not None, (
            "progress_bar must be initialized in upload_start"
        )
        upload_pbar.update(payload["chunk_size"])
        upload_pbar.refresh()

    @emitter.on("upload_end")
    @emitter.on("upload_failed")
    def upload_end(_: uploader.Progress) -> None:
        nonlocal upload_pbar
        if upload_pbar:
            upload_pbar.close()
        upload_pbar = None


def _setup_ipc(emitter: uploader.EventEmitter):
    @emitter.on("upload_start")
    def upload_start(payload: uploader.Progress):
        type: uploader.EventName = "upload_start"
        LOG.debug(f"{type.upper()}: {json.dumps(payload)}")
        ipc.send(type, payload)

    @emitter.on("upload_fetch_offset")
    def upload_fetch_offset(payload: uploader.Progress) -> None:
        type: uploader.EventName = "upload_fetch_offset"
        LOG.debug(f"{type.upper()}: {json.dumps(payload)}")
        ipc.send(type, payload)

    @emitter.on("upload_progress")
    def upload_progress(payload: uploader.Progress):
        type: uploader.EventName = "upload_progress"

        if LOG.isEnabledFor(logging.DEBUG):
            # In debug mode, we want to see the progress every 30 seconds
            # instead of every chunk (which is too verbose)
            INTERVAL_SECONDS = 30
            now = time.time()
            last_upload_progress_debug_at: float | None = T.cast(T.Dict, payload).get(
                "_last_upload_progress_debug_at"
            )
            if (
                last_upload_progress_debug_at is None
                or last_upload_progress_debug_at + INTERVAL_SECONDS < now
            ):
                LOG.debug(f"{type.upper()}: {json.dumps(payload)}")
                T.cast(T.Dict, payload)["_last_upload_progress_debug_at"] = now

        ipc.send(type, payload)

    @emitter.on("upload_end")
    def upload_end(payload: uploader.Progress) -> None:
        type: uploader.EventName = "upload_end"
        LOG.debug(f"{type.upper()}: {json.dumps(payload)}")
        ipc.send(type, payload)

    @emitter.on("upload_failed")
    def upload_failed(payload: uploader.Progress) -> None:
        type: uploader.EventName = "upload_failed"
        LOG.debug(f"{type.upper()}: {json.dumps(payload)}")
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
        now = time.time()
        payload["upload_start_time"] = now
        payload["upload_total_time"] = 0
        # These filed should be initialized in upload events like "upload_fetch_offset"
        # but since we disabled them for uploading images, so we initialize them here
        payload["upload_last_restart_time"] = now
        payload["upload_first_offset"] = 0

    @emitter.on("upload_fetch_offset")
    def collect_restart_time(payload: _APIStats) -> None:
        payload["upload_last_restart_time"] = time.time()
        payload["upload_first_offset"] = min(
            payload["offset"], payload.get("upload_first_offset", payload["offset"])
        )

    @emitter.on("upload_retrying")
    def collect_retrying(payload: _APIStats):
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
    # Note that stats[0]["total_sequence_count"] not always same as total_uploaded_sequence_count

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
        # TODO: rename sequences to total uploads
        "sequences": total_uploaded_sequence_count,
        "size": round(total_entity_size_mb, 4),
        "uploaded_size": round(total_uploaded_size_mb, 4),
        "speed": round(speed, 4),
        "time": round(total_upload_time, 4),
    }

    return upload_summary


def _show_upload_summary(stats: T.Sequence[_APIStats], errors: T.Sequence[Exception]):
    LOG.info("==> Upload summary")

    errors_by_type: dict[type[Exception], list[Exception]] = {}
    for error in errors:
        errors_by_type.setdefault(type(error), []).append(error)

    for error_type, error_list in errors_by_type.items():
        if error_type is UploadedAlready:
            LOG.info(
                f"Skipped {len(error_list)} already uploaded sequences (use --reupload to force re-upload)",
            )
        else:
            LOG.info(f"{len(error_list)} uploads failed due to {error_type.__name__}")

    if stats:
        grouped: dict[str, list[_APIStats]] = {}
        for stat in stats:
            grouped.setdefault(stat.get("file_type", "unknown"), []).append(stat)

        for file_type, typed_stats in grouped.items():
            if file_type == FileType.IMAGE.value:
                LOG.info(f"{len(typed_stats)} sequences uploaded")
            else:
                LOG.info(f"{len(typed_stats)} {file_type} uploaded")

        summary = _summarize(stats)
        LOG.info(f"{humanize.naturalsize(summary['size'] * 1024 * 1024)} read in total")
        LOG.info(
            f"{humanize.naturalsize(summary['uploaded_size'] * 1024 * 1024)} uploaded"
        )
        LOG.info(f"{summary['time']:.3f} seconds upload time")
    else:
        LOG.info("Nothing uploaded. Bye.")


def _api_logging_finished(summary: dict, dry_run: bool = False):
    if dry_run:
        return

    if constants.MAPILLARY_DISABLE_API_LOGGING:
        return

    action: api_v4.ActionType = "upload_finished_upload"

    with api_v4.create_client_session(disable_logging=True) as client_session:
        try:
            api_v4.log_event(client_session, action, summary)
        except requests.HTTPError as exc:
            LOG.warning(
                f"HTTPError from logging action {action}: {http.readable_http_error(exc)}"
            )
        except Exception:
            LOG.warning(f"Error from logging action {action}", exc_info=True)


def _api_logging_failed(payload: dict, exc: Exception, dry_run: bool = False):
    if dry_run:
        return

    if constants.MAPILLARY_DISABLE_API_LOGGING:
        return

    payload_with_reason = {**payload, "reason": exc.__class__.__name__}
    action: api_v4.ActionType = "upload_failed_upload"

    with api_v4.create_client_session(disable_logging=True) as client_session:
        try:
            api_v4.log_event(client_session, action, payload_with_reason)
        except requests.HTTPError as exc:
            LOG.warning(
                f"HTTPError from logging action {action}: {http.readable_http_error(exc)}"
            )
        except Exception:
            LOG.warning(f"Error from logging action {action}", exc_info=True)


_M = T.TypeVar("_M", bound=types.Metadata)


def _find_metadata_with_filename_existed_in(
    metadatas: T.Iterable[_M], paths: T.Iterable[Path]
) -> list[_M]:
    resolved_image_paths = set(p.resolve() for p in paths)
    return [d for d in metadatas if d.filename.resolve() in resolved_image_paths]


def _gen_upload_everything(
    mly_uploader: uploader.Uploader,
    metadatas: T.Sequence[types.Metadata],
    import_paths: T.Sequence[Path],
    skip_subfolders: bool,
):
    # Upload images
    image_metadatas = _find_metadata_with_filename_existed_in(
        (m for m in metadatas if isinstance(m, types.ImageMetadata)),
        utils.find_images(import_paths, skip_subfolders=skip_subfolders),
    )
    image_uploader = uploader.ImageSequenceUploader(
        mly_uploader.upload_options, emitter=mly_uploader.emitter
    )
    yield from image_uploader.upload_images(image_metadatas)

    # Upload videos
    video_metadatas = _find_metadata_with_filename_existed_in(
        (m for m in metadatas if isinstance(m, types.VideoMetadata)),
        utils.find_videos(import_paths, skip_subfolders=skip_subfolders),
    )
    yield from uploader.VideoUploader.upload_videos(mly_uploader, video_metadatas)

    # Upload zip files
    zip_paths = utils.find_zipfiles(import_paths, skip_subfolders=skip_subfolders)
    yield from uploader.ZipUploader.upload_zipfiles(mly_uploader, zip_paths)


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


def _continue_or_fail(ex: Exception) -> Exception:
    """
    Wrap the exception, or re-raise if it is a fatal error (i.e. there is no point to continue)
    """

    if isinstance(ex, uploader.SequenceError):
        return ex

    # Certain files not found or no permission
    if isinstance(ex, (FileNotFoundError, PermissionError)):
        return ex

    # Certain metadatas are not valid
    if isinstance(ex, exceptions.MapillaryMetadataValidationError):
        return ex

    # Fatal error: this is thrown after all retries
    if isinstance(ex, requests.ConnectionError):
        raise exceptions.MapillaryUploadConnectionError(str(ex)) from ex

    # Fatal error: this is thrown after all retries
    if isinstance(ex, requests.Timeout):
        raise exceptions.MapillaryUploadTimeoutError(str(ex)) from ex

    # Fatal error:
    if isinstance(ex, requests.HTTPError) and isinstance(
        ex.response, requests.Response
    ):
        if api_v4.is_auth_error(ex.response):
            raise exceptions.MapillaryUploadUnauthorizedError(
                api_v4.extract_auth_error_message(ex.response)
            ) from ex
        raise ex

    raise ex


def _load_descs(
    _metadatas_from_process: T.Sequence[types.MetadataOrError] | None,
    import_paths: T.Sequence[Path],
    desc_path: str | None,
) -> list[types.Metadata]:
    metadatas: list[types.Metadata]

    if _metadatas_from_process is not None:
        metadatas, _ = types.separate_errors(_metadatas_from_process)
    else:
        metadatas = _load_valid_metadatas_from_desc_path(import_paths, desc_path)

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


def _load_valid_metadatas_from_desc_path(
    import_paths: T.Sequence[Path], desc_path: str | None
) -> list[types.Metadata]:
    if desc_path is None:
        desc_path = _find_desc_path(import_paths)

    if desc_path == "-":
        try:
            metadatas = DescriptionJSONSerializer.deserialize_stream(sys.stdin.buffer)
        except json.JSONDecodeError as ex:
            raise exceptions.MapillaryInvalidDescriptionFile(
                f"Invalid JSON stream from {desc_path}: {ex}"
            ) from ex

    else:
        if not os.path.isfile(desc_path):
            raise exceptions.MapillaryFileNotFoundError(
                f"Description file not found: {desc_path}"
            )
        with open(desc_path, "rb") as fp:
            try:
                metadatas = DescriptionJSONSerializer.deserialize_stream(fp)
            except json.JSONDecodeError as ex:
                raise exceptions.MapillaryInvalidDescriptionFile(
                    f"Invalid JSON stream from {desc_path}: {ex}"
                ) from ex

    return metadatas


def _find_desc_path(import_paths: T.Sequence[Path]) -> str:
    if len(import_paths) == 1 and import_paths[0].is_dir():
        return str(import_paths[0].joinpath(constants.IMAGE_DESCRIPTION_FILENAME))

    if 1 < len(import_paths):
        raise exceptions.MapillaryBadParameterError(
            "The description path must be specified (with --desc_path) when uploading multiple paths"
        )
    else:
        raise exceptions.MapillaryBadParameterError(
            "The description path must be specified (with --desc_path) when uploading a single file"
        )
