# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""Pluggable GPS weight computation and weighted median interpolation.

This module implements the soft-weighting GPS interpolation algorithm
described in the design doc. Swap weight functions here without touching
the interpolation kernel or the pipeline glue.

All functions are pure — no I/O, no global state.
"""

from __future__ import annotations

import bisect
import math

MIN_SIGMA_XY = 0.5
DOPPLER_TOLERANCE_MPS = 2.0
MAX_SPEED_DISC = 20.0
TYPICAL_SPEED_MPS = 1.5

from .. import geo


def gps_distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return geo.gps_distance(p1, p2)


def compute_sample_sigma(
    hdop: float,
    fix: int,
    uere_nominal: float,
) -> tuple[float, float]:
    if fix == 0:
        return float("inf"), float("inf")
    if hdop <= 0:
        hdop = 10.0
    uere_eff = uere_nominal * (1.0 + 0.12 * hdop**1.5)
    sigma_xy = hdop * uere_eff
    sigma_z = 1.8 * hdop * uere_eff
    if fix == 2:
        sigma_xy *= 4.0
        sigma_z = float("inf")
    sigma_xy = max(sigma_xy, MIN_SIGMA_XY)
    return sigma_xy, sigma_z


def sample_weight(sigma_xy: float) -> float:
    if math.isinf(sigma_xy):
        return 0.0
    return 1.0 / (sigma_xy * sigma_xy)


def apply_speed_consistency(
    sigma_xys: list[float],
    times: list[float],
    lats: list[float],
    lons: list[float],
    doppler_speeds: list[float],
    max_abs_speed: float = 0.0,
) -> list[float]:
    """Penalize samples with implausible speed.

    Two checks:
    1. Absolute speed cap: if the GPS-reported Doppler speed exceeds
       max_abs_speed, the sample is almost certainly a multipath glitch.
       Set max_abs_speed=0 to auto-detect from median track speed × 5.
    2. Doppler discrepancy: if implied speed between consecutive samples
       exceeds the reported Doppler speed, inflate sigma.
    """
    adjusted = list(sigma_xys)

    # Auto-detect max plausible speed from the track itself
    if max_abs_speed <= 0:
        valid_speeds = [s for s in doppler_speeds if 0 < s < 50]
        if valid_speeds:
            med_speed = sorted(valid_speeds)[len(valid_speeds) // 2]
            max_abs_speed = max(med_speed * 5.0, 10.0)
        else:
            max_abs_speed = 10.0

    # Two-pass: forward then backward, using last accepted sample as reference
    for direction in (1, -1):
        rng = range(len(times)) if direction == 1 else range(len(times) - 1, -1, -1)
        last_good_i = -1
        for i in rng:
            if math.isinf(adjusted[i]):
                continue

            # Check 1: absolute speed cap on Doppler
            if doppler_speeds[i] > max_abs_speed:
                adjusted[i] = float("inf")
                continue

            # Check 2: implied speed from last accepted sample
            if last_good_i >= 0:
                dt = abs(times[i] - times[last_good_i])
                if dt > 0:
                    v_implied = (
                        gps_distance(
                            (lats[last_good_i], lons[last_good_i]),
                            (lats[i], lons[i]),
                        )
                        / dt
                    )
                    if v_implied > max_abs_speed:
                        adjusted[i] = float("inf")
                        continue

                    v_doppler = doppler_speeds[i]
                    disc = min(
                        max(0.0, v_implied - v_doppler - DOPPLER_TOLERANCE_MPS),
                        MAX_SPEED_DISC,
                    )
                    if disc > 0:
                        adjusted[i] *= 1.0 + 1.5 * disc

            last_good_i = i
    return adjusted


def weighted_median(
    values: list[float],
    lo: int,
    hi: int,
    weights: list[float],
) -> float:
    n = hi - lo
    if n <= 0:
        raise ValueError("empty range")
    paired = sorted(
        ((values[lo + i], weights[i]) for i in range(n)),
        key=lambda x: x[0],
    )
    total = sum(weights)
    if total <= 0:
        return values[lo]
    half = total / 2.0
    cumsum = 0.0
    for val, w in paired:
        cumsum += w
        if cumsum >= half:
            return val
    return paired[-1][0]


def weighted_median_unwrapped(
    lons: list[float],
    lo: int,
    hi: int,
    weights: list[float],
) -> float:
    n = hi - lo
    raw = [lons[lo + i] for i in range(n)]
    if max(raw) - min(raw) > 180.0:
        raw = [v + 360.0 if v < 0 else v for v in raw]
    paired = sorted(zip(raw, weights), key=lambda x: x[0])
    total = sum(weights)
    if total <= 0:
        return lons[lo]
    half = total / 2.0
    cumsum = 0.0
    for val, w in paired:
        cumsum += w
        if cumsum >= half:
            return ((val + 180.0) % 360.0) - 180.0
    result = paired[-1][0]
    return ((result + 180.0) % 360.0) - 180.0


def _find_nearest_valid(
    weights: list[float], start: int, direction: int, limit: int = -1
) -> int:
    """Find the nearest index with positive weight, searching in direction."""
    i = start
    while 0 <= i < len(weights) and (limit < 0 or i != limit):
        if weights[i] > 0:
            return i
        i += direction
    return -1


def weighted_interpolate(
    t: float,
    times: list[float],
    lats: list[float],
    lons: list[float],
    weights: list[float],
    sigma_xys: list[float],
    tau: float = 1.0,
) -> tuple[float, float, float]:
    window = 3.0 * tau
    inv_2tau2 = 1.0 / (2.0 * tau * tau)

    lo = bisect.bisect_left(times, t - window)
    hi = bisect.bisect_right(times, t + window)

    if lo >= hi:
        # Find nearest points with positive weight on each side
        left_i = _find_nearest_valid(weights, lo - 1, -1)
        right_i = _find_nearest_valid(weights, hi, 1, len(times))
        if left_i < 0 and right_i < 0:
            return 0.0, 0.0, float("inf")
        if left_i < 0:
            return lats[right_i], lons[right_i], sigma_xys[right_i]
        if right_i < 0:
            return lats[left_i], lons[left_i], sigma_xys[left_i]
        dt_total = times[right_i] - times[left_i]
        w = (t - times[left_i]) / dt_total if dt_total > 0 else 0.5
        lat = lats[left_i] + (lats[right_i] - lats[left_i]) * w
        lon = lons[left_i] + (lons[right_i] - lons[left_i]) * w
        nearest_dt = min(abs(t - times[left_i]), abs(t - times[right_i]))
        accuracy = (
            max(sigma_xys[left_i], sigma_xys[right_i]) + nearest_dt * TYPICAL_SPEED_MPS
        )
        return lat, lon, max(accuracy, MIN_SIGMA_XY)

    combined_w: list[float] = []
    for i in range(lo, hi):
        dt = t - times[i]
        k = math.exp(-dt * dt * inv_2tau2)
        combined_w.append(weights[i] * k)

    total_w = sum(combined_w)
    if total_w <= 0:
        valid = _find_nearest_valid(weights, lo, 1, hi)
        if valid < 0:
            valid = _find_nearest_valid(weights, lo - 1, -1)
        if valid < 0:
            return 0.0, 0.0, float("inf")
        return lats[valid], lons[valid], sigma_xys[valid]

    lat = weighted_median(lats, lo, hi, combined_w)
    lon = weighted_median_unwrapped(lons, lo, hi, combined_w)
    accuracy = 1.0 / math.sqrt(total_w)
    return lat, lon, max(accuracy, MIN_SIGMA_XY)
