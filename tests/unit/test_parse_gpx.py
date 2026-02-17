# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import tempfile
from pathlib import Path

from mapillary_tools import geo, telemetry
from mapillary_tools.geotag.utils import parse_gpx

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data"
GPX_FILE = FIXTURE_DIR / "gpx" / "sf_30km_h.gpx"


def test_parse_gpx_creates_camm_gps_points():
    tracks = parse_gpx(GPX_FILE)
    assert len(tracks) == 1
    track = tracks[0]
    assert len(track) > 0

    for point in track:
        assert isinstance(point, telemetry.CAMMGPSPoint)
        assert point.time_gps_epoch == point.time
        assert point.gps_fix_type == 3  # all points have <ele>
        assert point.horizontal_accuracy == 0.0
        assert point.vertical_accuracy == 0.0
        assert point.velocity_east == 0.0
        assert point.velocity_north == 0.0
        assert point.velocity_up == 0.0
        assert point.speed_accuracy == 0.0
        assert point.angle is None
        assert point.alt is not None


def test_parse_gpx_without_elevation():
    gpx_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="37.7749" lon="-122.4194">
        <time>2025-01-01T00:00:00Z</time>
      </trkpt>
      <trkpt lat="37.7750" lon="-122.4195">
        <time>2025-01-01T00:00:01Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gpx", delete=False) as f:
        f.write(gpx_content)
        f.flush()
        tracks = parse_gpx(Path(f.name))

    assert len(tracks) == 1
    for point in tracks[0]:
        assert isinstance(point, telemetry.CAMMGPSPoint)
        assert point.gps_fix_type == 2
        assert point.alt is None


def test_parse_gpx_skips_points_without_time():
    gpx_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="37.7749" lon="-122.4194">
        <time>2025-01-01T00:00:00Z</time>
      </trkpt>
      <trkpt lat="37.7750" lon="-122.4195">
      </trkpt>
      <trkpt lat="37.7751" lon="-122.4196">
        <time>2025-01-01T00:00:02Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gpx", delete=False) as f:
        f.write(gpx_content)
        f.flush()
        tracks = parse_gpx(Path(f.name))

    assert len(tracks) == 1
    # The point without <time> should be skipped
    assert len(tracks[0]) == 2


def test_parse_gpx_multiple_segments():
    gpx_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="37.7749" lon="-122.4194">
        <time>2025-01-01T00:00:00Z</time>
      </trkpt>
    </trkseg>
    <trkseg>
      <trkpt lat="37.7800" lon="-122.4100">
        <time>2025-01-01T00:01:00Z</time>
      </trkpt>
      <trkpt lat="37.7801" lon="-122.4101">
        <time>2025-01-01T00:01:01Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gpx", delete=False) as f:
        f.write(gpx_content)
        f.flush()
        tracks = parse_gpx(Path(f.name))

    assert len(tracks) == 2
    assert len(tracks[0]) == 1
    assert len(tracks[1]) == 2
