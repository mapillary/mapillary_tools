# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""Robust GPS track smoothing: reject physically-impossible jumps, then run a
sigma-weighted constant-velocity Kalman filter + RTS smoother over the whole track.

This is the "middle ground" between the old hard noise filter (which DELETED points
and cut corners) and the soft weight-only approach (which kept all jitter): every
point is replaced by a smoothed estimate that trusts good fixes tightly and bad
fixes loosely, so outlier spikes and jitter are removed while the real shape is kept.

NOTE: uses numpy for the 4x4 linear algebra. Pure-python port is a follow-up before
upstreaming (mapillary_tools core has no numpy dependency).
"""
from __future__ import annotations

import dataclasses
import logging
import math
import typing as T

from .. import geo
from ..telemetry import GPSPoint
from . import gps_weigher

LOG = logging.getLogger(__name__)


def _speed_gate(lats: list[float], lons: list[float], times: list[float], cap_mps: float) -> list[bool]:
    ok = [True] * len(times)
    last = 0
    for i in range(1, len(times)):
        dt = times[i] - times[last]
        if dt <= 0:
            ok[i] = False
            continue
        d = geo.gps_distance((lats[last], lons[last]), (lats[i], lons[i]))
        if d / dt > cap_mps:
            ok[i] = False
        else:
            last = i
    return ok


def _kalman_rts(xy, t, sig, q_accel):
    import numpy as np

    n = len(xy)
    H = np.array([[1, 0, 0, 0], [0, 0, 1, 0]], float)
    x = np.zeros((n, 4)); P = np.zeros((n, 4, 4))
    xp = np.zeros((n, 4)); Pp = np.zeros((n, 4, 4))
    Fs = [np.eye(4) for _ in range(n)]
    x[0] = [xy[0][0], 0.0, xy[0][1], 0.0]
    P[0] = np.diag([100.0, 100.0, 100.0, 100.0])
    xp[0] = x[0]; Pp[0] = P[0]
    for i in range(1, n):
        dt = max(t[i] - t[i - 1], 1e-3)
        F = np.array([[1, dt, 0, 0], [0, 1, 0, 0], [0, 0, 1, dt], [0, 0, 0, 1]], float)
        Fs[i] = F
        qb = q_accel * np.array([[dt**3 / 3, dt**2 / 2], [dt**2 / 2, dt]])
        Q = np.zeros((4, 4)); Q[:2, :2] = qb; Q[2:, 2:] = qb
        xpred = F @ x[i - 1]; Ppred = F @ P[i - 1] @ F.T + Q
        xp[i] = xpred; Pp[i] = Ppred
        s = sig[i]
        if s is None or math.isinf(s):
            x[i] = xpred; P[i] = Ppred
        else:
            R = np.diag([s * s, s * s])
            y = np.array([xy[i][0], xy[i][1]]) - H @ xpred
            S = H @ Ppred @ H.T + R
            K = Ppred @ H.T @ np.linalg.inv(S)
            x[i] = xpred + K @ y
            P[i] = (np.eye(4) - K @ H) @ Ppred
    xs = x.copy()
    for i in range(n - 2, -1, -1):
        F = Fs[i + 1]
        C = P[i] @ F.T @ np.linalg.inv(Pp[i + 1])
        xs[i] = x[i] + C @ (xs[i + 1] - xp[i + 1])
    return [(float(xs[i, 0]), float(xs[i, 2])) for i in range(n)]


def smooth_gps_points(
    sequence: T.Sequence[GPSPoint],
    q_accel: float = 4.0,
    uere_nominal: float = 3.0,
    cap_mps: float | None = None,
) -> list[GPSPoint]:
    """Return a new GPSPoint list with smoothed lat/lon (same length, same times)."""
    if len(sequence) < 3:
        return list(sequence)

    lats = [p.lat for p in sequence]
    lons = [p.lon for p in sequence]
    times = [p.time for p in sequence]

    # per-sample sigma; fix==0 -> inf (followed by dynamics only, not trusted)
    sig = []
    for p in sequence:
        hdop = (p.precision / 100.0) if p.precision is not None else 10.0
        fix_val = p.fix.value if p.fix is not None else 0
        s, _ = gps_weigher.compute_sample_sigma(hdop, fix_val, uere_nominal)
        sig.append(s)

    # auto speed cap: 5x median ground speed, floor 15 m/s
    if cap_mps is None:
        spds = sorted(p.ground_speed for p in sequence if p.ground_speed and p.ground_speed > 0)
        med = spds[len(spds) // 2] if spds else 3.0
        cap_mps = max(med * 5.0, 15.0)

    ok = _speed_gate(lats, lons, times, cap_mps)
    for i in range(len(sig)):
        if not ok[i]:
            sig[i] = float("inf")  # gated points: dynamics-only

    # project to local ENU meters
    lat0, lon0 = lats[0], lons[0]
    mlat = 111320.0
    mlon = 111320.0 * math.cos(math.radians(lat0))
    xy = [((lo - lon0) * mlon, (la - lat0) * mlat) for la, lo in zip(lats, lons)]

    try:
        sm = _kalman_rts(xy, times, sig, q_accel)
    except ImportError:
        # numpy is not a hard dependency of mapillary_tools; if it is unavailable,
        # degrade gracefully to the unsmoothed points rather than failing.
        LOG.warning("gps_smoother: numpy unavailable; returning unsmoothed GPS points")
        return list(sequence)

    out: list[GPSPoint] = []
    for p, (x, y) in zip(sequence, sm):
        out.append(dataclasses.replace(p, lat=y / mlat + lat0, lon=x / mlon + lon0))
    return out
