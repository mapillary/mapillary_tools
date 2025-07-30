from __future__ import annotations

import json
import logging
import string
import typing as T
from pathlib import Path

from . import constants, types
from .serializer.description import DescriptionJSONSerializer

JSONDict = T.Dict[str, T.Union[str, int, float, None]]

LOG = logging.getLogger(__name__)


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
        Path(constants.MAPILLARY_UPLOAD_HISTORY_PATH)
        .joinpath(subfolder)
        .joinpath(f"{basename}.json")
    )


def read_history_record(md5sum: str) -> None | T.Dict[str, T.Any]:
    if not constants.MAPILLARY_UPLOAD_HISTORY_PATH:
        return None

    path = history_desc_path(md5sum)

    if not path.is_file():
        return None

    with path.open("r") as fp:
        try:
            return json.load(fp)
        except json.JSONDecodeError as ex:
            LOG.error(f"Failed to read upload history {path}: {ex}")
            return None


def write_history(
    md5sum: str,
    params: JSONDict,
    summary: JSONDict,
    metadatas: T.Sequence[types.Metadata] | None = None,
) -> None:
    if not constants.MAPILLARY_UPLOAD_HISTORY_PATH:
        return
    path = history_desc_path(md5sum)
    LOG.debug("Writing upload history: %s", path)
    path.resolve().parent.mkdir(parents=True, exist_ok=True)
    history: dict[str, T.Any] = {"params": params, "summary": summary}
    if metadatas is not None:
        history["descs"] = [
            DescriptionJSONSerializer.as_desc(metadata) for metadata in metadatas
        ]
    with open(path, "w") as fp:
        fp.write(json.dumps(history))
