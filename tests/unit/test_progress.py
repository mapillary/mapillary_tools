# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations


def test_align_gps_filename_stacks_with_total():
    from mapillary_tools.progress import align_progress_bars

    fill = "█"
    file_bar = (
        f"Extracting GPS (GX020129.GPX):  43%|{fill * 10}{' ' * 10}|"
        " 1.21M/2.80M [00:08<00:11,  154kB/s]"
    )
    overall = (
        f"Total progress (2/13 GX020129.MP4):   8%|{fill * 2}{' ' * 18}|"
        " 10.0G/130G [00:48<32:07, 63.7MB/s]"
    )
    out = align_progress_bars([file_bar, overall], 120)
    assert out[0].find("GX") == out[1].find("GX")
    assert out[0].index("%|") == out[1].index("%|")
    assert out[0].rindex("|") == out[1].rindex("|")


def test_align_progress_bars_shares_bar_columns():
    from mapillary_tools.progress import align_progress_bars, split_progress_bar
    from tqdm.utils import disp_len

    fill = "\u2588"
    file_bar = (
        f"Extracting frames (GX020129.MP4):  50%|{fill * 10}{' ' * 10}|"
        " 1228/2456 [01:37<01:37, 12.7 frames/s]"
    )
    overall = (
        f"Total progress (2/13 GX020129.MP4):  12%|{fill * 3}{' ' * 17}|"
        " 16.1G/130G [03:36<32:07, 63.7MB/s]"
    )
    out = align_progress_bars([file_bar, overall], 120)
    parts0 = split_progress_bar(out[0])
    parts1 = split_progress_bar(out[1])
    assert parts0 is not None and parts1 is not None
    prefix0, pct0, bar0, right0 = parts0
    prefix1, pct1, bar1, right1 = parts1
    assert disp_len(prefix0) == disp_len(prefix1)
    assert disp_len(pct0) == disp_len(pct1)
    assert disp_len(bar0) == disp_len(bar1)
    assert disp_len(right0) == disp_len(right1)
    assert out[0].find("GX") == out[1].find("GX")
    assert out[0].index("%|") == out[1].index("%|")
    assert out[0].rindex("|") == out[1].rindex("|")

def test_pad_to_width_clears_previous_bar_tail():
    from mapillary_tools.progress import overlay_cr, pad_to_width, wrap_to_width

    assert pad_to_width("hi", 8) == "hi      "
    assert overlay_cr("abcdefgh", "xy") == "xy" + "cdefgh"
    wrapped = wrap_to_width("abcdefghij", 4)
    assert wrapped == ["abcd", "efgh", "ij  "]
    assert wrap_to_width("abcd", 8) == ["abcd    "]

def test_console_screen_commit_then_live():
    import io

    from mapillary_tools.progress import ConsoleScreen

    buf = io.StringIO()
    screen = ConsoleScreen(fp=buf, disabled=False)
    screen.commit("Input #0, mov,mp4")
    screen.set_live("frame=    1 fps=1.0")
    text = buf.getvalue()
    assert "Input #0, mov,mp4" in text

def test_console_screen_wraps_long_commit(monkeypatch):
    import io

    from mapillary_tools import progress as prog

    monkeypatch.setattr(prog, "_UP", "\x1b[A")

    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    buf = _Tty()
    screen = prog.ConsoleScreen(fp=buf, disabled=False)
    monkeypatch.setattr(screen, "ncols", lambda: 10)
    screen.commit("abcdefghijklmnop")
    text = buf.getvalue()
    assert "abcdefghij" in text
    assert "klmnop" in text

def test_file_bar_is_drawn_above_overall():
    from mapillary_tools.progress import ConsoleScreen

    screen = ConsoleScreen(disabled=True)
    screen.attach_overall(lambda: "Total progress: 8%")
    screen.attach_file(lambda: "Extracting frames: 23%")
    assert screen._live_lines() == [
        "Extracting frames: 23%",
        "Total progress: 8%",
    ]
    screen.set_live("frame=    1")
    assert screen._live_lines()[0] == "frame=    1"

def test_live_lines_align_file_and_overall_bars(monkeypatch):
    from mapillary_tools.progress import ConsoleScreen, align_progress_bars

    fill = "\u2588"
    file_row = (
        f"Extracting frames (GX020129.MP4):  50%|{fill * 8}{' ' * 8}|"
        " 1228/2456 [01:37<01:37, 12.7 frames/s]"
    )
    overall_row = (
        f"Total progress (2/13 GX020129.MP4):  12%|{fill * 2}{' ' * 14}|"
        " 16.1G/130G [03:36<32:07, 63.7MB/s]"
    )
    screen = ConsoleScreen(disabled=True)
    monkeypatch.setattr(screen, "ncols", lambda: 110)
    screen.attach_file(lambda: file_row)
    screen.attach_overall(lambda: overall_row)
    assert screen._live_lines() == align_progress_bars([file_row, overall_row], 110)
