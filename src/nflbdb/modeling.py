"""Modelling helpers for Combine-to-NFL inference.

The three traps this module exists to avoid
-------------------------------------------
1. **Draft position is a confounder and a mediator at once.** Teams see the same
   Combine data we do, so draft slot is downstream of Combine performance; it then
   determines opportunity, which determines every counting outcome. Regressing an NFL
   outcome on a Combine feature without handling draft slot measures "did teams already
   know this", and controlling for it naively blocks the very pathway you care about.
   :func:`residualize` and :func:`draft_capital_baseline` make the choice explicit, and
   the honest framing is usually *incremental* value over a draft-slot baseline.
2. **Survivorship.** Outcomes only exist for players who got snaps. The 13 prospects
   with no NFL snap, and the long tail with <100, are not missing at random.
   :func:`opportunity_weights` and the snap-count floor make the selection visible.
3. **Three draft classes is not a large sample.** Any model validated in-sample on
   2023-2025 is overfit. :func:`leave_one_class_out` is the default evaluation, and
   every transform must be fitted inside the fold (see ``fit_on_train``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np
import polars as pl

__all__ = [
    "residualize",
    "draft_capital_baseline",
    "DRAFT_VALUE_ANCHORS",
    "draft_value_curve",
    "opportunity_weights",
    "leave_one_class_out",
    "CVResult",
    "incremental_r2",
    "shrink_to_group_mean",
]


# --------------------------------------------------------------------------------------
# Draft capital
# --------------------------------------------------------------------------------------

#: Jimmy Johnson-style anchors (overall pick -> relative value). Used only to give draft
#: slot a sane non-linear shape; the exact curve matters far less than *not* treating
#: pick 1 and pick 33 as 32 units apart on a linear scale.
DRAFT_VALUE_ANCHORS: dict[int, float] = {
    1: 3000, 5: 1700, 10: 1300, 16: 1000, 20: 850, 32: 590,
    45: 450, 64: 270, 96: 116, 128: 42, 160: 27, 192: 14, 224: 6, 259: 2,
}


def draft_value_curve(overall_pick: np.ndarray, undrafted_value: float = 0.5) -> np.ndarray:
    """Map overall pick -> draft-capital value, log-interpolated between anchors.

    UDFAs (null pick) get ``undrafted_value``, below the last pick, which keeps them in
    the model instead of dropping the most interesting part of the cohort.
    """
    p = np.asarray(overall_pick, dtype=float)
    xs = np.array(sorted(DRAFT_VALUE_ANCHORS))
    ys = np.array([DRAFT_VALUE_ANCHORS[k] for k in xs], dtype=float)
    out = np.exp(np.interp(np.clip(p, xs[0], xs[-1]), xs, np.log(ys)))
    return np.where(np.isnan(p), undrafted_value, out)


def draft_capital_baseline(
    df: pl.DataFrame, outcome: str, *, pick_col: str = "draft_overall_pick"
) -> pl.DataFrame:
    """Add ``draft_value`` and ``log_draft_value`` columns, the baseline every metric must beat.

    The question a front office actually asks is not "does this movement feature predict
    NFL performance" -- draft position already does that -- but "does it predict
    performance *that draft position missed*". That is a residual question, and this is
    the column it is measured against.
    """
    dv = draft_value_curve(df[pick_col].to_numpy())
    return df.with_columns([
        pl.Series("draft_value", dv),
        pl.Series("log_draft_value", np.log(np.maximum(dv, 1e-3))),
        pl.col(pick_col).is_null().alias("is_udfa"),
    ])


# --------------------------------------------------------------------------------------
# Residualization
# --------------------------------------------------------------------------------------

def residualize(
    y: np.ndarray, X: np.ndarray, *, add_intercept: bool = True, return_model: bool = False
):
    """OLS residuals of ``y`` on ``X``, NaN-safe.

    Used two ways in this project:
    * residualize a Combine feature on body mass and the official drill time, to isolate
      the part of the movement signature the stopwatch does not already capture;
    * residualize an NFL outcome on draft capital, to ask what draft position missed.
    """
    y = np.asarray(y, float)
    X = np.atleast_2d(np.asarray(X, float))
    if X.shape[0] != y.shape[0]:
        X = X.T
    m = np.isfinite(y) & np.isfinite(X).all(axis=1)
    out = np.full_like(y, np.nan)
    if m.sum() <= X.shape[1] + 1:
        return (out, None) if return_model else out

    Xm = X[m]
    if add_intercept:
        Xm = np.column_stack([np.ones(Xm.shape[0]), Xm])
    beta, *_ = np.linalg.lstsq(Xm, y[m], rcond=None)
    out[m] = y[m] - Xm @ beta
    return (out, beta) if return_model else out


def incremental_r2(y: np.ndarray, X_base: np.ndarray, X_full: np.ndarray) -> dict[str, float]:
    """R^2 of a base model, a full model, and the increment between them.

    This is the headline number for "does tracking add anything the stopwatch didn't".
    Report it, not a bare correlation.
    """
    y = np.asarray(y, float)
    Xb = np.atleast_2d(np.asarray(X_base, float))
    Xf = np.atleast_2d(np.asarray(X_full, float))
    if Xb.shape[0] != y.shape[0]:
        Xb = Xb.T
    if Xf.shape[0] != y.shape[0]:
        Xf = Xf.T
    m = np.isfinite(y) & np.isfinite(Xb).all(axis=1) & np.isfinite(Xf).all(axis=1)
    if m.sum() < max(Xf.shape[1] + 2, 8):
        return {"r2_base": np.nan, "r2_full": np.nan, "delta_r2": np.nan, "n": float(m.sum())}

    def _r2(X):
        A = np.column_stack([np.ones(m.sum()), X[m]])
        beta, *_ = np.linalg.lstsq(A, y[m], rcond=None)
        resid = y[m] - A @ beta
        sst = ((y[m] - y[m].mean()) ** 2).sum()
        return float(1 - (resid ** 2).sum() / sst) if sst > 0 else np.nan

    rb, rf = _r2(Xb), _r2(Xf)
    return {"r2_base": rb, "r2_full": rf, "delta_r2": rf - rb, "n": float(m.sum())}


# --------------------------------------------------------------------------------------
# Opportunity / survivorship
# --------------------------------------------------------------------------------------

def opportunity_weights(snaps: np.ndarray, *, floor: int = 50, cap: int | None = None) -> np.ndarray:
    """Weights proportional to snaps played, so a 40-snap rookie does not outvote a starter.

    A per-snap rate computed over 40 snaps has enormous sampling error. Weighting by
    exposure is the minimum correction; a hierarchical model that shrinks small-sample
    players toward their group mean (see :func:`shrink_to_group_mean`) is better.
    """
    s = np.asarray(snaps, float)
    w = np.where(np.isfinite(s), np.maximum(s, 0.0), 0.0)
    if cap is not None:
        w = np.minimum(w, cap)
    return np.where(w >= floor, w, 0.0)


def shrink_to_group_mean(
    values: np.ndarray, n_obs: np.ndarray, *, prior_strength: float | None = None
) -> np.ndarray:
    """Empirical-Bayes shrinkage of per-player rates toward the cohort mean.

    ``prior_strength`` defaults to a method-of-moments estimate: the number of
    observations at which a player's own rate and the group mean get equal weight. This
    is the cheapest defensible way to stop a 3-target rookie with 1 catch from topping
    the leaderboard.
    """
    v = np.asarray(values, float)
    n = np.asarray(n_obs, float)
    m = np.isfinite(v) & np.isfinite(n) & (n > 0)
    if m.sum() < 3:
        return v
    grand = float(np.average(v[m], weights=n[m]))
    if prior_strength is None:
        between = float(np.var(v[m]))
        within = float(np.average((v[m] - grand) ** 2, weights=n[m]))
        prior_strength = max(1.0, within / between) if between > 1e-12 else 10.0
    out = np.full_like(v, np.nan)
    out[m] = (n[m] * v[m] + prior_strength * grand) / (n[m] + prior_strength)
    return out


# --------------------------------------------------------------------------------------
# Cross-validation
# --------------------------------------------------------------------------------------

@dataclass
class CVResult:
    folds: list[dict]

    @property
    def mean(self) -> dict[str, float]:
        keys = {k for f in self.folds for k, v in f.items() if isinstance(v, (int, float))}
        return {k: float(np.nanmean([f.get(k, np.nan) for f in self.folds])) for k in sorted(keys)}

    def to_frame(self) -> pl.DataFrame:
        return pl.DataFrame(self.folds)


def leave_one_class_out(
    df: pl.DataFrame,
    fit_predict: Callable[[pl.DataFrame, pl.DataFrame], dict],
    *,
    class_col: str = "draft_year",
) -> CVResult:
    """Leave-one-draft-class-out CV.

    With only three draft classes this is the only honest split available: it tests
    whether a relationship found in 2023-2024 holds in a class the model never saw,
    which is exactly the question a team asks before using a metric on the 2027 class.

    ``fit_predict(train, test) -> dict of metrics``. **Fit every transform inside the
    callback**, including standardization -- centering drill features using the held-out
    class's distribution makes the evaluation transductive and inflates the result.
    """
    folds = []
    for cls in sorted(df[class_col].unique().to_list()):
        train = df.filter(pl.col(class_col) != cls)
        test = df.filter(pl.col(class_col) == cls)
        if train.height == 0 or test.height == 0:
            continue
        res = fit_predict(train, test)
        folds.append({class_col: cls, "n_train": train.height, "n_test": test.height, **res})
    return CVResult(folds)


def group_kfold(df: pl.DataFrame, group_col: str, k: int = 5, seed: int = 0) -> Iterator[tuple]:
    """K-fold that never splits a player across folds."""
    rng = np.random.default_rng(seed)
    groups = df[group_col].unique().to_numpy()
    rng.shuffle(groups)
    for fold in np.array_split(groups, k):
        test_mask = pl.col(group_col).is_in(fold.tolist())
        yield df.filter(~test_mask), df.filter(test_mask)
