import json
import logging
import os
import string
import typing as T
from pathlib import Path

from . import constants, types

JSONDict = T.Dict[str, T.Union[str, int, float, None]]

LOG = logging.getLogger(__name__)
MAPILLARY_UPLOAD_HISTORY_PATH = os.getenv(
    "MAPILLARY_UPLOAD_HISTORY_PATH",
    os.path.join(
        constants.USER_DATA_DIR,
        "upload_history",
    ),
)


def _validate_hexdigits(md5sum: str):
    try:
        assert set(md5sum).issubset(string.hexdigits)
        assert 4 <= len(md5sum)
        _ = int(md5sum, 16)
    except Exception:
        raise ValueError(f"Invalid md5sum {md5sum}")


def history_desc_path(md5sum: str) -> Path:
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
    return history_desc_path(md5sum).is_file()


def write_history(
    md5sum: str,
    params: JSONDict,
    summary: JSONDict,
    metadatas: T.Optional[T.Sequence[types.Metadata]] = None,
) -> None:
    if not MAPILLARY_UPLOAD_HISTORY_PATH:
        return
    path = history_desc_path(md5sum)
    LOG.debug("Writing upload history: %s", path)
    path.resolve().parent.mkdir(parents=True, exist_ok=True)
    history: T.Dict[str, T.Any] = {
        "params": params,
        "summary": summary,
    }
    if metadatas is not None:
        history["descs"] = [types.as_desc(metadata) for metadata in metadatas]
    with open(path, "w") as fp:
        fp.write(json.dumps(history))
