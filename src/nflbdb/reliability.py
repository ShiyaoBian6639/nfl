"""Reliability of a movement metric.

Why this matters more than it looks
-----------------------------------
A Combine movement metric is a *measurement*, and an NFL analytics staffer's first
question about any new measurement is "is it stable?". A feature that correlates with
NFL outcomes but does not correlate with *itself* across two reps of the same drill is
noise that happened to land. Reliability also caps validity: the correlation between a
metric and any outcome is bounded by sqrt(reliability), so a feature with ICC = 0.3
cannot correlate above ~0.55 with anything, no matter how good the theory is.

The Combine data supports this directly: many drills have two attempts per prospect,
which is a ready-made test-retest design. :func:`drill_reliability_table` turns that
into the table that belongs in the submission.
"""

from __future__ import annotations

import numpy as np
import polars as pl

__all__ = [
    "icc_2_1",
    "spearman_brown",
    "test_retest",
    "attenuation_ceiling",
    "drill_reliability_table",
    "bootstrap_ci",
]


def icc_2_1(ratings: np.ndarray) -> dict[str, float]:
    """ICC(2,1): two-way random effects, absolute agreement, single measurement.

    ``ratings`` is ``(n_subjects, k_repeats)``; rows with any NaN are dropped. This is
    the right ICC form for "the same athlete did the drill twice and we want to know how
    much of the spread is between athletes rather than between reps".
    """
    r = np.asarray(ratings, dtype=float)
    r = r[~np.isnan(r).any(axis=1)]
    n, k = r.shape
    if n < 3 or k < 2:
        return {"icc": np.nan, "n": float(n), "k": float(k)}

    grand = r.mean()
    ms_rows = k * ((r.mean(axis=1) - grand) ** 2).sum() / (n - 1)
    ms_cols = n * ((r.mean(axis=0) - grand) ** 2).sum() / (k - 1)
    resid = r - r.mean(axis=1, keepdims=True) - r.mean(axis=0, keepdims=True) + grand
    ms_err = (resid ** 2).sum() / ((n - 1) * (k - 1))

    denom = ms_rows + (k - 1) * ms_err + k * (ms_cols - ms_err) / n
    return {
        "icc": float((ms_rows - ms_err) / denom) if denom > 0 else np.nan,
        "n": float(n), "k": float(k),
        "ms_between_subjects": float(ms_rows), "ms_error": float(ms_err),
    }


def spearman_brown(r: float, k: float = 2.0) -> float:
    """Project a single-rep reliability ``r`` to the reliability of ``k`` averaged reps."""
    if not np.isfinite(r):
        return np.nan
    return float(k * r / (1 + (k - 1) * r))


def test_retest(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """Pearson and Spearman correlation between two reps, with the n actually used."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 4:
        return {"pearson": np.nan, "spearman": np.nan, "n": float(m.sum())}
    from scipy.stats import pearsonr, spearmanr
    return {
        "pearson": float(pearsonr(a[m], b[m]).statistic),
        "spearman": float(spearmanr(a[m], b[m]).statistic),
        "n": float(m.sum()),
    }


def attenuation_ceiling(rel_x: float, rel_y: float = 1.0) -> float:
    """Maximum observable correlation given the reliability of each variable.

    Report this next to any Combine-to-NFL correlation. "r = 0.28" reads as weak until
    you say the ceiling given measurement error is 0.55 -- then it reads as half of the
    available signal.
    """
    if not (np.isfinite(rel_x) and np.isfinite(rel_y)) or rel_x <= 0 or rel_y <= 0:
        return np.nan
    return float(np.sqrt(rel_x * rel_y))


def drill_reliability_table(
    features: pl.DataFrame,
    feature_cols: list[str],
    *,
    by: str = "drill_name",
    subject: str = "nfl_id",
    rep: str = "attempt",
    min_subjects: int = 8,
) -> pl.DataFrame:
    """Test-retest reliability of each feature within each drill.

    Uses the first two available reps per prospect. Returns one row per
    (drill, feature) with ICC(2,1), the rep-to-rep correlation, the Spearman-Brown
    projection for a 2-rep average, and the resulting validity ceiling.
    """
    rows = []
    for (drill,), g in features.group_by([by], maintain_order=True):
        wide = (
            g.sort([subject, rep])
             .group_by(subject, maintain_order=True)
             .agg([pl.col(c).head(2).alias(c) for c in feature_cols] + [pl.len().alias("_n")])
             .filter(pl.col("_n") >= 2)
        )
        if wide.height < min_subjects:
            continue
        for c in feature_cols:
            vals = wide[c].to_list()
            arr = np.array([[v[0], v[1]] for v in vals if v is not None and len(v) >= 2], float)
            if arr.shape[0] < min_subjects:
                continue
            icc = icc_2_1(arr)
            tr = test_retest(arr[:, 0], arr[:, 1])
            rows.append({
                "drill_name": str(drill), "feature": c,
                "n_subjects": int(icc["n"]),
                "icc_2_1": round(icc["icc"], 3) if np.isfinite(icc["icc"]) else None,
                "retest_r": round(tr["pearson"], 3) if np.isfinite(tr["pearson"]) else None,
                "sb_2rep": round(spearman_brown(icc["icc"]), 3) if np.isfinite(icc["icc"]) else None,
                "validity_ceiling": round(attenuation_ceiling(icc["icc"]), 3)
                                    if np.isfinite(icc["icc"]) and icc["icc"] > 0 else None,
            })
    if not rows:
        return pl.DataFrame(schema={"drill_name": pl.Utf8, "feature": pl.Utf8,
                                    "n_subjects": pl.Int64, "icc_2_1": pl.Float64,
                                    "retest_r": pl.Float64, "sb_2rep": pl.Float64,
                                    "validity_ceiling": pl.Float64})
    return pl.DataFrame(rows).sort(["drill_name", "icc_2_1"], descending=[False, True], nulls_last=True)


def bootstrap_ci(
    stat_fn, *arrays: np.ndarray, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float, float]:
    """Percentile bootstrap CI for any statistic of paired arrays.

    Returns ``(point, lo, hi)``. With n in the low hundreds -- which is every position
    group in this dataset -- a correlation without an interval is not a finding.
    """
    rng = np.random.default_rng(seed)
    arrs = [np.asarray(a, float) for a in arrays]
    mask = np.ones(arrs[0].shape[0], bool)
    for a in arrs:
        mask &= np.isfinite(a)
    arrs = [a[mask] for a in arrs]
    n = arrs[0].size
    if n < 4:
        return (np.nan, np.nan, np.nan)
    point = float(stat_fn(*arrs))
    boots = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        try:
            boots[i] = stat_fn(*[a[idx] for a in arrs])
        except Exception:
            boots[i] = np.nan
    lo, hi = np.nanpercentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return (point, float(lo), float(hi))
