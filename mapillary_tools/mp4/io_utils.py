import io
import typing as T


class ChainedIO(io.IOBase):
    # is the chained stream seekable?
    _streams: T.Sequence[io.IOBase]
    # the beginning offset of the current stream
    _begin_offset: int
    # offset after SEEK_END
    _offset_after_seek_end: int
    # index of the current stream
    _idx: int

    def __init__(self, streams: T.Sequence[io.IOBase]):
        for s in streams:
            assert s.readable(), f"stream {s} must be readable"
            assert s.seekable(), f"stream {s} must be seekable"
            # required, otherwise inconsistent results when seeking back and forth
            s.seek(0, io.SEEK_SET)
        self._streams = streams
        self._begin_offset = 0
        self._offset_after_seek_end = 0
        self._idx = 0

    def _seek_next_stream(self) -> None:
        """
        seek to the end of the current stream, and seek to the beginning of the next stream
        """
        if self._idx < len(self._streams):
            s = self._streams[self._idx]
            ssize = s.seek(0, io.SEEK_END)

            # update index
            self._idx += 1

            # seek to the beginning of the next stream
            if self._idx < len(self._streams):
                self._streams[self._idx].seek(0, io.SEEK_SET)

            # update offset
            self._begin_offset += ssize

    def read(self, n: int = -1) -> bytes:
        acc = []

        while self._idx < len(self._streams):
            data = self._streams[self._idx].read(n)
            acc.append(data)
            if n == -1:
                self._seek_next_stream()
            elif len(data) < n:
                n = n - len(data)
                self._seek_next_stream()
            else:
                break

        return b"".join(acc)

    def seekable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def readable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_CUR:
            if offset < 0:
                raise ValueError("negative offset not supported yet")

            while self._idx < len(self._streams):
                s = self._streams[self._idx]
                co = s.tell()
                eo = s.seek(0, io.SEEK_END)
                assert co <= eo
                if offset <= eo - co:
                    s.seek(co + offset, io.SEEK_SET)
                    offset = 0
                    break
                self._seek_next_stream()
                offset = offset - (eo - co)

            if 0 < offset:
                self._offset_after_seek_end += offset

        elif whence == io.SEEK_SET:
            self._idx = 0
            self._begin_offset = 0
            self._offset_after_seek_end = 0
            self._streams[self._idx].seek(0, io.SEEK_SET)
            if offset:
                self.seek(offset, io.SEEK_CUR)

        elif whence == io.SEEK_END:
            self._idx = 0
            self._begin_offset = 0
            self._offset_after_seek_end = 0
            while self._idx < len(self._streams):
                self._seek_next_stream()
            if offset:
                self.seek(offset, io.SEEK_CUR)

        else:
            raise IOError("invalid whence")

        return self.tell()

    def tell(self) -> int:
        if self._idx < len(self._streams):
            rel_offset = self._streams[self._idx].tell()
        else:
            rel_offset = self._offset_after_seek_end

        return self._begin_offset + rel_offset

    def close(self) -> None:
        for b in self._streams:
            b.close()
        return None


class SlicedIO(io.IOBase):
    __slots__ = ("_source", "_begin_offset", "_rel_offset", "_size")

    _source: T.BinaryIO
    _begin_offset: int
    _rel_offset: int
    _size: int

    def __init__(self, source: T.BinaryIO, offset: int, size: int) -> None:
        assert source.readable(), "source stream must be readable"
        assert source.seekable(), "source stream must be seekable"
        self._source = source
        if offset < 0:
            raise ValueError(f"negative offset {offset}")
        self._begin_offset = offset
        self._rel_offset = 0
        self._size = size

    def read(self, n: int = -1) -> bytes:
        if self._rel_offset < self._size:
            self._source.seek(self._begin_offset + self._rel_offset, io.SEEK_SET)
            remaining = self._size - self._rel_offset
            max_read = remaining if n == -1 else min(n, remaining)
            data = self._source.read(max_read)
            self._rel_offset += len(data)
            return data
        else:
            return b""

    def seekable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._rel_offset

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            new_offset = offset
            if new_offset < 0:
                raise ValueError(f"negative seek value {new_offset}")
        elif whence == io.SEEK_CUR:
            new_offset = max(0, self._rel_offset + offset)
        elif whence == io.SEEK_END:
            new_offset = max(0, self._size + offset)
        else:
            raise IOError("invalid whence")
        self._rel_offset = new_offset
        return self._rel_offset
