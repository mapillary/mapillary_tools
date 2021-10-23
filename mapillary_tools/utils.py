import typing as T
import hashlib


def md5sum_fp(fp: T.IO[bytes]) -> str:
    md5 = hashlib.md5()
    while True:
        buf = fp.read(1024 * 1024 * 32)
        if not buf:
            break
        md5.update(buf)
    return md5.hexdigest()


def md5sum_bytes(data: bytes) -> str:
    md5 = hashlib.md5()
    md5.update(data)
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
