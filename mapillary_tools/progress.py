# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import logging
import re
import shutil
import sys
import threading
import typing as T
from contextlib import contextmanager

from tqdm import tqdm
from tqdm.utils import RE_ANSI, _term_move_up, disp_len, disp_trim

from .utils import get_app_name


LOG = logging.getLogger(__name__)

# tqdm default unicode uses 1/8-width fractions (▏▎▍…). Full block only.
BAR_ASCII = " \u2588"

_UP = _term_move_up()


def pad_to_width(text: str, ncols: int) -> str:
    """Fit *text* to *ncols* and pad with spaces so a previous bar cannot linger."""
    text = text.replace("\r", "").replace("\n", "").rstrip()
    if ncols <= 0:
        return text
    n = disp_len(text)
    if n < ncols:
        return text + " " * (ncols - n)
    if n > ncols:
        return disp_trim(text, ncols)
    return text


@contextmanager
def count_bar(
    desc: str,
    unit: str = " files",
    total: float | None = None,
) -> T.Generator[tqdm, None, None]:
    """tqdm bar for scans / prepares (same style as Extracting images)."""
    bar = tqdm(
        desc=desc,
        unit=unit,
        total=total,
        ascii=BAR_ASCII,
        disable=LOG.isEnabledFor(logging.DEBUG),
        mininterval=0.2,
        miniters=1,
        leave=True,
    )
    try:
        yield bar
    finally:
        bar.close()


def wrap_to_width(text: str, ncols: int) -> list[str]:
    """Split *text* into display rows of at most *ncols*, padding each row."""
    text = text.replace("\r", "").replace("\n", "").rstrip()
    if ncols <= 0:
        return [text] if text else [""]
    rows: list[str] = []
    buf = ""
    width = 0
    i = 0
    n = len(text)
    while i < n:
        m = RE_ANSI.match(text, i)
        if m is not None:
            buf += m.group(0)
            i = m.end()
            continue
        ch = text[i]
        w = disp_len(ch)
        if width and width + w > ncols:
            rows.append(pad_to_width(buf, ncols))
            buf = ""
            width = 0
        buf += ch
        width += w
        i += 1
    if buf or not rows:
        rows.append(pad_to_width(buf, ncols))
    return rows


_PAREN_COUNTER = re.compile(r"^\(\d+/\d+\s+")


def split_progress_bar(line: str) -> tuple[str, str, str, str] | None:
    """Split a tqdm line into ``(prefix, percentage including %, bar, right)``.

    ``percentage`` is tqdm's ``{percentage:3.0f}%`` field (4 columns), so
    padding spaces belong to *prefix* and survive a second split.
    """
    marker = "%|"
    i = line.find(marker)
    if i < 0:
        return None
    rest = line[i + 2 :]
    j = rest.find("|")
    if j < 0:
        return None
    left = line[: i + 1]
    if len(left) >= 4 and left.endswith("%"):
        prefix, pct = left[:-4], left[-4:]
    else:
        prefix, pct = left, ""
    return prefix, pct, rest[:j], rest[j + 1 :]


def _filename_col(prefix: str) -> int | None:
    """Display column where the name inside ``(...)`` starts.

    ``(2/13 GX020129.MP4)`` starts at ``GX``; ``(GX020129.GPX)`` starts
    just after ``(``.
    """
    i = prefix.find("(")
    if i < 0:
        return None
    m = _PAREN_COUNTER.match(prefix[i:])
    start = i + m.end() if m else i + 1
    return disp_len(prefix[:start])


def align_progress_bars(lines: T.Sequence[str], ncols: int) -> list[str]:
    """Pad so filenames stack and both bars start and end on the same columns."""
    parts = [split_progress_bar(s) for s in lines]
    if any(p is None for p in parts) or len(parts) < 2:
        return list(lines)
    parsed = T.cast(list[tuple[str, str, str, str]], parts)
    cols = [_filename_col(prefix) for prefix, _, _, _ in parsed]
    if all(c is not None for c in cols):
        max_col = max(T.cast(list[int], cols))
        aligned: list[tuple[str, str, str, str]] = []
        for (prefix, pct, bar, right), col in zip(parsed, cols):
            pad = max_col - T.cast(int, col)
            if pad > 0:
                i = prefix.find("(")
                prefix = prefix[:i] + (" " * pad) + prefix[i:]
            aligned.append((prefix, pct, bar, right))
        parsed = aligned
    max_prefix = max(disp_len(prefix) for prefix, _, _, _ in parsed)
    max_pct = max(disp_len(pct) for _, pct, _, _ in parsed)
    max_right = max(disp_len(right.rstrip()) for _, _, _, right in parsed)
    bar_w = max(ncols - max_prefix - max_pct - max_right - 2, 1)
    out: list[str] = []
    fill = "\u2588"
    for prefix, pct, bar, right in parsed:
        ratio = bar.count(fill) / max(disp_len(bar), 1)
        nfill = min(bar_w, max(0, int(round(ratio * bar_w))))
        new_bar = fill * nfill + " " * (bar_w - nfill)
        prefix_p = prefix + " " * (max_prefix - disp_len(prefix))
        pct_p = " " * (max_pct - disp_len(pct)) + pct
        right_p = right.rstrip() + " " * (max_right - disp_len(right.rstrip()))
        out.append(f"{prefix_p}{pct_p}|{new_bar}|{right_p}")
    return out


def overlay_cr(old: str, new: str) -> str:
    """Apply a CR update: *new* overwrites *old* from column 0."""
    if not old:
        return new
    if len(new) >= len(old):
        return new
    return new + old[len(new) :]


class ConsoleScreen:
    """One live FFmpeg line plus 0..2 progress lines, all drawn by us.

    FFmpeg ``\\n`` lines are committed (padded to the terminal width, then
    the progress rows are redrawn). FFmpeg ``\\r`` updates the live line
    buffer and the whole block is redrawn.
    """

    def __init__(self, fp: T.TextIO | None = None, *, disabled: bool = False) -> None:
        self._fp = fp if fp is not None else sys.stderr
        self._lock = threading.Lock()
        self._live = ""
        self._file_bar: T.Callable[[], str] | None = None
        self._overall_bar: T.Callable[[], str] | None = None
        self._rows = 0
        self.disabled = disabled
        self._log_restore: list[tuple[logging.Handler, T.Any]] = []

    def ncols(self) -> int:
        try:
            return max(int(shutil.get_terminal_size().columns), 20)
        except Exception:
            return 80

    def attach_file(self, render: T.Callable[[], str]) -> None:
        with self._lock:
            self._file_bar = render
            self._paint()

    def attach_overall(self, render: T.Callable[[], str]) -> None:
        with self._lock:
            self._overall_bar = render
            self._paint()

    def detach_file(self, render: T.Callable[[], str]) -> None:
        with self._lock:
            if self._file_bar is render:
                self._file_bar = None
            self._paint()

    def detach_overall(self, render: T.Callable[[], str]) -> None:
        with self._lock:
            if self._overall_bar is render:
                self._overall_bar = None
            self._paint()

    def set_live(self, text: str) -> None:
        with self._lock:
            self._live = overlay_cr(self._live, text.replace("\r", "").rstrip())
            self._paint()

    def clear_live(self) -> None:
        with self._lock:
            self._live = ""
            self._paint()

    def commit(self, text: str) -> None:
        """Write finished line(s) above the live block, then redraw progress once."""
        lines = [
            raw.rstrip()
            for raw in text.replace("\r", "\n").split("\n")
            if raw.rstrip()
        ]
        if not lines:
            return
        with self._lock:
            self._paint(commits=lines)

    def ingest_ffmpeg(self, history: T.Sequence[str], live: str | None) -> None:
        """Apply a drained FFmpeg burst: all history lines, then one progress redraw."""
        with self._lock:
            if live is not None:
                self._live = overlay_cr(
                    self._live, live.replace("\r", "").rstrip()
                )
            self._paint(commits=list(history))

    def redraw(self) -> None:
        with self._lock:
            self._paint()

    def _live_lines(self) -> list[str]:
        lines: list[str] = []
        if self._live:
            lines.append(self._live)
        bar_rows: list[str] = []
        for render in (self._file_bar, self._overall_bar):
            if render is None:
                continue
            try:
                row = render()
            except Exception:
                continue
            if row:
                bar_rows.append(row.replace("\r", "").rstrip("\n"))
        if len(bar_rows) >= 2:
            bar_rows = align_progress_bars(bar_rows, self.ncols())
        lines.extend(bar_rows)
        return lines

    def _paint(self, commits: T.Sequence[str] | None = None) -> None:
        if self.disabled:
            return
        if commits is None:
            commits = ()
        ncols = self.ncols()
        fp = self._fp
        interactive = bool(getattr(fp, "isatty", lambda: False)()) and bool(_UP)
        new_lines = self._live_lines()
        if not interactive:
            for line in commits:
                fp.write(line + "\n")
            fp.flush()
            return
        if self._rows > 0:
            fp.write("\r" + _UP * (self._rows - 1))
        commit_rows: list[str] = []
        for line in commits:
            commit_rows.extend(wrap_to_width(line, ncols))
        for line in commit_rows:
            fp.write(line + "\n")
        for i, line in enumerate(new_lines):
            fp.write(pad_to_width(line, ncols))
            if i != len(new_lines) - 1:
                fp.write("\n")
        old = self._rows
        painted = len(new_lines)
        extra = max(0, old - len(commit_rows) - painted)
        if extra:
            if painted:
                fp.write("\n")
            for _ in range(extra):
                fp.write(pad_to_width("", ncols) + "\n")
            fp.write(_UP * (extra + (1 if painted else 0)))
        self._rows = painted
        fp.flush()

    def close(self) -> None:
        with self._lock:
            self._live = ""
            self._file_bar = None
            self._overall_bar = None
            if not self.disabled and self._rows > 0:
                ncols = self.ncols()
                fp = self._fp
                if getattr(fp, "isatty", lambda: False)() and _UP:
                    fp.write("\r" + _UP * (self._rows - 1))
                    for i in range(self._rows):
                        fp.write(pad_to_width("", ncols))
                        if i != self._rows - 1:
                            fp.write("\n")
                    fp.write("\n")
                self._rows = 0
                fp.flush()
        self._restore_logs()

    def redirect_logs(self) -> None:
        logger = logging.getLogger(get_app_name())
        stream = _ScreenLogStream(self)
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                self._log_restore.append((handler, handler.stream))
                handler.stream = stream

    def _restore_logs(self) -> None:
        for handler, stream in self._log_restore:
            handler.stream = stream
        self._log_restore = []


class _ScreenLogStream:
    def __init__(self, screen: ConsoleScreen) -> None:
        self._screen = screen

    def write(self, s: str) -> int:
        if s:
            self._screen.commit(s)
        return len(s)

    def flush(self) -> None:
        pass


_screen: ConsoleScreen | None = None
_screen_lock = threading.Lock()


def _ensure_screen(*, disabled: bool | None = None) -> ConsoleScreen:
    global _screen
    with _screen_lock:
        if _screen is None:
            if disabled is None:
                disabled = LOG.isEnabledFor(logging.DEBUG)
            _screen = ConsoleScreen(disabled=bool(disabled))
            if not _screen.disabled:
                _screen.redirect_logs()
        return _screen


def _release_screen_if_idle() -> None:
    global _screen
    with _screen_lock:
        if _screen is None:
            return
        if _screen._file_bar is not None or _screen._overall_bar is not None:
            return
        _screen.close()
        _screen = None


def screen_is_active() -> bool:
    return _screen is not None and not _screen.disabled


def bar_is_active() -> bool:
    return screen_is_active()


def display_is_bound() -> bool:
    return _screen is not None


def ingest_ffmpeg_stderr(
    history: T.Sequence[str], live: str | None
) -> None:
    """Commit drained FFmpeg lines, then redraw progress once."""
    if _screen is None:
        for line in history:
            if line:
                tqdm.write(line, file=sys.stderr)
        return
    if not history and live is None:
        return
    _screen.ingest_ffmpeg(history, live)


def write_above(msg: str) -> None:
    """Print *msg* as a finished console line (padded), then redraw progress."""
    text = msg.rstrip("\n")
    if not text:
        return
    if _screen is not None:
        _screen.commit(text)
        return
    tqdm.write(text, file=sys.stderr)


def set_live_line(msg: str) -> None:
    """Update the in-place FFmpeg line (``frame=`` / CR status)."""
    text = msg.rstrip("\n")
    if _screen is None:
        return
    if not text:
        _screen.clear_live()
        return
    _screen.set_live(text)


def suspend_display() -> None:
    """Clear the live FFmpeg line; progress rows stay and will be redrawn."""
    if _screen is not None:
        _screen.clear_live()


def resume_display() -> None:
    if _screen is not None:
        _screen.redraw()
