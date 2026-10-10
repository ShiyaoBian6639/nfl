"""Turn raw Combine drill trajectories into per-attempt movement features.

This is the module that does the thing the competition is actually about: the stopwatch
gives you one number per drill, the 10 Hz trace gives you the *shape* of the movement
that produced it. Two prospects can run an identical 6.95 three-cone while braking,
turning and re-accelerating completely differently -- and only one of those profiles
survives contact with NFL route-running.

Every feature here is computed from the smoothed ``(t, x, y)`` trajectory via
:mod:`nflbdb.kinematics`, not from the vendor ``s``/``a`` columns, so the filter is
explicit and reportable. Vendor columns are carried alongside as a cross-check.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from .config import SUSPECT_DRILL_YEARS
from .kinematics import (
    Kinematics,
    derivatives,
    detect_cuts,
    sprint_profile,
    to_uniform_grid,
)

__all__ = [
    "attempt_features",
    "extract_attempt_features",
    "standardize_within",
    "GENERIC_FEATURES",
]

#: features computed for every drill regardless of type
GENERIC_FEATURES = (
    "duration_s", "path_length_yd", "net_displacement_yd", "path_efficiency",
    "peak_speed", "mean_speed", "t_to_peak_speed", "speed_at_10pct", "speed_at_90pct",
    "peak_accel", "peak_decel", "mean_abs_a_tan", "mean_abs_a_norm",
    "accel_decel_ratio", "peak_jerk",
    "total_heading_change_deg", "max_turn_rate_deg_s", "min_turn_radius_yd",
    "n_cuts", "time_in_cuts_s", "frac_time_in_cuts",
    "mean_cut_speed_lost_pct", "max_cut_speed_lost_pct",
    "mean_cut_peak_decel", "mean_cut_peak_reaccel", "mean_cut_duration_s",
    "mean_cut_recovery_s", "cod_deficit_s",
)


def _safe(x: float | np.floating) -> float:
    v = float(x)
    return v if np.isfinite(v) else float("nan")


def attempt_features(
    t: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    drill_name: str = "",
    cutoff_hz: float = 2.0,
    cut_kwargs: dict | None = None,
) -> dict[str, float]:
    """Full feature vector for one drill attempt.

    ``cod_deficit_s`` is the change-of-direction deficit: time actually spent in cuts
    minus the time the same distance would have taken at the athlete's own peak speed.
    It isolates *agility* from *straight-line speed*, which is exactly the separation the
    stopwatch cannot make -- a fast athlete with a large deficit is a straight-line
    runner, a slower one with a small deficit is a mover.
    """
    tg, (xg, yg), grid = to_uniform_grid(t, x, y)
    k: Kinematics = derivatives(tg, xg, yg, cutoff_hz=cutoff_hz)
    cuts = detect_cuts(k, **(cut_kwargs or {}))

    dist = np.sum(np.hypot(np.diff(k.x), np.diff(k.y)))
    net = float(np.hypot(k.x[-1] - k.x[0], k.y[-1] - k.y[0]))
    dur = float(tg[-1] - tg[0])
    peak = float(np.nanmax(k.speed))
    i_peak = int(np.nanargmax(k.speed))

    f: dict[str, float] = {
        "n_frames": float(grid["n_frames_out"]),
        "n_gaps": float(grid["n_gaps"]),
        "max_gap_frames": float(grid["max_gap_frames"]),
        "duration_s": dur,
        "path_length_yd": _safe(dist),
        "net_displacement_yd": net,
        "path_efficiency": _safe(net / dist) if dist > 0 else np.nan,
        "peak_speed": peak,
        "mean_speed": _safe(np.nanmean(k.speed)),
        "t_to_peak_speed": float(tg[i_peak] - tg[0]),
        "speed_at_10pct": _safe(np.interp(0.10, np.linspace(0, 1, k.speed.size), k.speed)),
        "speed_at_90pct": _safe(np.interp(0.90, np.linspace(0, 1, k.speed.size), k.speed)),
        "peak_accel": _safe(np.nanmax(k.a_tan)),
        "peak_decel": _safe(np.nanmin(k.a_tan)),
        "mean_abs_a_tan": _safe(np.nanmean(np.abs(k.a_tan))),
        "mean_abs_a_norm": _safe(np.nanmean(np.abs(k.a_norm))),
        "peak_jerk": _safe(np.nanmax(k.jerk)),
        "total_heading_change_deg": _safe(np.rad2deg(np.nansum(np.abs(np.diff(k.heading))))),
        "max_turn_rate_deg_s": _safe(np.rad2deg(np.nanmax(np.abs(k.omega)))),
        "min_turn_radius_yd": _safe(1.0 / np.nanmax(k.kappa)) if np.nanmax(k.kappa) > 1e-6 else np.inf,
        "vendor_peak_s": np.nan,   # filled by the caller if the vendor column is available
    }
    denom = abs(f["peak_decel"])
    f["accel_decel_ratio"] = _safe(f["peak_accel"] / denom) if denom > 1e-6 else np.nan

    # ---- cut-level aggregation
    f["n_cuts"] = float(len(cuts))
    if cuts:
        tic = float(sum(c.duration_s for c in cuts))
        f.update({
            "time_in_cuts_s": tic,
            "frac_time_in_cuts": _safe(tic / dur) if dur > 0 else np.nan,
            "mean_cut_speed_lost_pct": _safe(np.mean([c.speed_lost_pct for c in cuts])),
            "max_cut_speed_lost_pct": _safe(np.max([c.speed_lost_pct for c in cuts])),
            "mean_cut_peak_decel": _safe(np.mean([c.peak_decel for c in cuts])),
            "mean_cut_peak_reaccel": _safe(np.mean([c.peak_reaccel for c in cuts])),
            "mean_cut_duration_s": _safe(np.mean([c.duration_s for c in cuts])),
            "mean_cut_entry_speed": _safe(np.mean([c.entry_speed for c in cuts])),
            "mean_cut_min_speed": _safe(np.mean([c.min_speed for c in cuts])),
            "mean_cut_turn_radius_yd": _safe(np.mean([c.min_turn_radius for c in cuts
                                                      if np.isfinite(c.min_turn_radius)] or [np.nan])),
            # a cut the athlete never recovers from has recovery_time_s = nan; if that is
            # every cut in the attempt, np.nanmean would warn on an empty slice
            "mean_cut_recovery_s": _safe(np.nanmean(_rec)) if (
                _rec := [c.recovery_time_s for c in cuts if np.isfinite(c.recovery_time_s)]
            ) else np.nan,
            "n_reversals": float(sum(c.is_reversal for c in cuts)),
            "mean_lateral_excursion_yd": _safe(np.nanmean([c.lateral_excursion_yd for c in cuts])),
            "min_lateral_excursion_yd": _safe(np.nanmin([c.lateral_excursion_yd for c in cuts])),
        })
        # change-of-direction deficit
        cut_dist = 0.0
        for c in cuts:
            seg = slice(c.i_start, c.i_end + 1)
            cut_dist += float(np.sum(np.hypot(np.diff(k.x[seg]), np.diff(k.y[seg]))))
        f["cod_deficit_s"] = _safe(tic - cut_dist / peak) if peak > 0 else np.nan
    else:
        for key in ("time_in_cuts_s", "frac_time_in_cuts", "mean_cut_speed_lost_pct",
                    "max_cut_speed_lost_pct", "mean_cut_peak_decel", "mean_cut_peak_reaccel",
                    "mean_cut_duration_s", "mean_cut_entry_speed", "mean_cut_min_speed",
                    "mean_cut_turn_radius_yd", "mean_cut_recovery_s", "cod_deficit_s",
                    "n_reversals", "mean_lateral_excursion_yd", "min_lateral_excursion_yd"):
            f[key] = np.nan

    # ---- drill-specific
    if "FORTY" in drill_name.upper():
        sp = sprint_profile(tg, k.speed)
        f.update({
            "sprint_vmax": sp.vmax, "sprint_tau": sp.tau, "sprint_r2": sp.r2,
            "sprint_amax": sp.amax, "sprint_pmax_rel": sp.pmax_rel,
            "sprint_t10": sp.t_to_10yd, "sprint_t20": sp.t_to_20yd, "sprint_t40": sp.t_to_40yd,
            "sprint_converged": float(sp.converged),
        })
    return f


def extract_attempt_features(
    combine_tracking: pl.LazyFrame | pl.DataFrame,
    *,
    cutoff_hz: float = 2.0,
    drop_suspect_drill_years: bool = True,
    min_frames: int = 10,
    progress: bool = True,
) -> pl.DataFrame:
    """Apply :func:`attempt_features` to every drill attempt.

    One row per ``event_id``. Suspect drill/year combinations (see
    ``config.SUSPECT_DRILL_YEARS``) are dropped by default rather than silently fed into
    a model: a truncated rep produces a *plausible-looking* near-zero braking value,
    which is the most dangerous kind of missing data.
    """
    lf = combine_tracking.lazy() if isinstance(combine_tracking, pl.DataFrame) else combine_tracking
    df = (
        lf.filter(pl.col("entity_type") == "PLAYER")
          .select(["draft_year", "event_id", "nfl_id", "drill_type", "drill_name",
                   "attempt", "time", "x", "y", "s", "a"])
          .collect()
          .sort(["event_id", "time"])
    )

    if drop_suspect_drill_years:
        before = df["event_id"].n_unique()
        for name, yr in SUSPECT_DRILL_YEARS:
            df = df.filter(~((pl.col("drill_name").cast(pl.Utf8) == name)
                             & (pl.col("draft_year") == yr)))
        dropped = before - df["event_id"].n_unique()
        if dropped and progress:
            print(f"  dropped {dropped} attempts from suspect drill/years {SUSPECT_DRILL_YEARS}")

    rows = []
    groups = df.partition_by("event_id", as_dict=True)
    for i, (key, g) in enumerate(groups.items()):
        if g.height < min_frames:
            continue
        t = g["time"].dt.timestamp("ms").to_numpy() / 1000.0
        head = g.row(0, named=True)
        try:
            feats = attempt_features(
                t, g["x"].to_numpy(), g["y"].to_numpy(),
                drill_name=str(head["drill_name"]), cutoff_hz=cutoff_hz,
            )
        except Exception as exc:
            feats = {"error": str(exc)}
        feats["vendor_peak_s"] = float(g["s"].max())
        feats["vendor_peak_a"] = float(g["a"].max())
        feats["vendor_min_a"] = float(g["a"].min())
        rows.append({
            "event_id": head["event_id"], "nfl_id": head["nfl_id"],
            "draft_year": head["draft_year"], "drill_type": str(head["drill_type"]),
            "drill_name": str(head["drill_name"]), "attempt": head["attempt"],
            **feats,
        })
        if progress and (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(groups)} attempts")

    return pl.DataFrame(rows, infer_schema_length=None)


def standardize_within(
    df: pl.DataFrame,
    cols: list[str],
    by: tuple[str, ...] = ("drill_name", "draft_year"),
    *,
    suffix: str = "_z",
    robust: bool = True,
) -> pl.DataFrame:
    """Z-score ``cols`` within ``by`` groups.

    Standardizing within ``(drill_name, draft_year)`` is mandatory here, not stylistic:
    the 2025 Combine export is not quantized the same way as 2023/2024 and shows a
    systematic speed offset, so a raw cross-class comparison partly measures the
    vendor's export pipeline. ``robust=True`` uses median / 1.4826*MAD, which keeps one
    mis-tracked rep from rescaling an entire draft class.

    Note for modelling: fit this on training folds only. Standardizing with the held-out
    draft class in the pool turns leave-one-draft-class-out CV into transductive
    evaluation and will overstate out-of-sample performance.
    """
    exprs = []
    for c in cols:
        if c not in df.columns:
            continue
        if robust:
            med = pl.col(c).median().over(by)
            mad = (pl.col(c) - med).abs().median().over(by) * 1.4826
            exprs.append(
                pl.when(mad > 1e-9).then((pl.col(c) - med) / mad).otherwise(None).alias(c + suffix)
            )
        else:
            mu, sd = pl.col(c).mean().over(by), pl.col(c).std().over(by)
            exprs.append(
                pl.when(sd > 1e-9).then((pl.col(c) - mu) / sd).otherwise(None).alias(c + suffix)
            )
    return df.with_columns(exprs)
