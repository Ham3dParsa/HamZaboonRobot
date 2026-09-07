"""Capacity verdict helpers for the load simulation (locked plan scale/plan-load-sim-capacity, T1).

Pure functions, no I/O, no production modules touched. Tool-only: pure
helpers under direct unit test in ``tests/test_load_sim_capacity.py``;
driver wiring for report verdicts is a later ticket, not this module.

Margins (explicit, never hidden):
- ``CPU_CLOCK_MARGIN`` (2.0) — dev-machine cores measure ~2x faster than
  deploy cores, so measured CPU cost is doubled inside
  :func:`capacity_for_cpu` before sizing.
- ``SAFETY_MARGIN`` (1.5) — applied ONLY via :func:`apply_margin`, and
  every report line using it carries a ``margin_included`` label.
"""

from __future__ import annotations

import math

# 2x dev-core-faster margin: measured CPU seconds are multiplied by this
# inside capacity_for_cpu (not hidden in the caller).
CPU_CLOCK_MARGIN = 2.0

# Safety margin for capacity verdicts: applied ONLY via apply_margin();
# verdict outputs label margin-included lines explicitly.
SAFETY_MARGIN = 1.5

# Deploy RAM bands under test (MB).
RAM_BANDS_MB = (256, 512, 1024)


def apply_margin(value: float) -> float:
    """Scale ``value`` by ``SAFETY_MARGIN`` (explicit, labeled by callers)."""
    return float(value) * SAFETY_MARGIN


def capacity_for_cpu(cpu_budget: float, journeys_per_sec: float) -> int:
    """Return max sustainable peak users for a CPU budget (margin-included).

    Units (documented):
    - ``cpu_budget`` — CPU milliseconds available per wall-clock second
      (e.g. ``1000.0`` = one saturated core).
    - ``journeys_per_sec`` — CPU milliseconds consumed per second by ONE
      peak user, derived from the replay as
      ``mean(cpu_ms_per_journey) * peak arrivals per second per user``.
    - Returns ``floor(cpu_budget / (journeys_per_sec * CPU_CLOCK_MARGIN))``;
      ``0`` when either input is non-positive.

    The ``CPU_CLOCK_MARGIN`` doubling happens HERE (explicit constant,
    stated in the docstring) — callers must not pre-inflate the inputs.
    Apply :func:`apply_margin` on top only when a safety-margined line is
    wanted, and label that line ``margin_included``.
    """
    if cpu_budget <= 0 or journeys_per_sec <= 0:
        return 0
    return int(math.floor(cpu_budget / (journeys_per_sec * CPU_CLOCK_MARGIN)))


def verdict_for_bands(
    rss_baseline: float,
    rss_per_concurrent_session: float,
    peak_concurrent: float,
    deploy_overlap_x2: bool = True,
) -> dict:
    """Return per-band (256/512/1024MB) pass/fail with arithmetic shown.

    All inputs/outputs in MB. Projected peak
    ``= rss_baseline + rss_per_concurrent_session * peak_concurrent [* 2
    deploy-overlap]``, then safety-margined via :func:`apply_margin`.
    The verdict compares the MARGIN-INCLUDED projection against the band;
    each entry shows the full arithmetic string (raw numbers, margin
    factor, comparison) so the verdict is auditable. Pure function.
    """
    overlap = 2 if deploy_overlap_x2 else 1
    overlap_txt = "*2 overlap" if deploy_overlap_x2 else "no overlap"
    raw = (
        float(rss_baseline)
        + float(rss_per_concurrent_session) * float(peak_concurrent) * overlap
    )
    projected = apply_margin(raw)
    out: dict = {}
    for band in RAM_BANDS_MB:
        verdict = "pass" if projected <= band else "fail"
        out[band] = {
            "band_mb": band,
            "projected_mb": raw,
            "projected_mb_margin_included": projected,
            "verdict": verdict,
            "arithmetic": (
                f"{rss_baseline} + {rss_per_concurrent_session}"
                f"*{peak_concurrent} ({overlap_txt}) = {raw:.2f} MB; "
                f"x{SAFETY_MARGIN} margin = {projected:.2f} MB "
                f"(margin-included) vs {band} MB band -> {verdict}"
            ),
        }
    return out
