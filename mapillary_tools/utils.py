import json
import typing as T
import hashlib

from . import types


def md5sum_fp(fp: T.IO[bytes]) -> str:
    md5 = hashlib.md5()
    while True:
        buf = fp.read(1024 * 1024 * 32)
        if not buf:
            break
        md5.update(buf)
    return md5.hexdigest()


def file_md5sum(path: str) -> str:
    with open(path, "rb") as fp:
        return md5sum_fp(fp)


_IT = T.TypeVar("_IT")


def separate_by_bool(
    f: T.Callable[[_IT], bool], s: T.Iterable[_IT]
) -> T.Tuple[T.List[_IT], T.List[_IT]]:
    yes, no = [], []
    for x in s:
        if f(x):
            yes.append(x)
        else:
            no.append(x)
    return yes, no


def update_image_md5sum(descs: T.List[types.ImageDescriptionFile]) -> None:
    for desc in descs:
        md5sum = desc.get("md5sum")
        if md5sum is None:
            desc["md5sum"] = file_md5sum(desc["filename"])


def calculate_sequence_md5sum(descs: T.List[types.ImageDescriptionFile]):
    excluded_properties = ["MAPPhotoUUID", "MAPSequenceUUID"]
    md5 = hashlib.md5()
    for desc in descs:
        assert "md5sum" in desc
        md5.update(desc["md5sum"].encode("utf-8"))
        new_desc = {
            k: v
            for k, v in desc.items()
            if k.startswith("MAP") and k not in excluded_properties
        }
        md5.update(json.dumps(new_desc, sort_keys=True).encode("utf-8"))
    return md5.hexdigest()
