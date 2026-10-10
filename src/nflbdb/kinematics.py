"""Trajectory signal processing for 10 Hz player tracking.

Why this module exists
----------------------
The ``s`` and ``a`` columns shipped with the tracking data are vendor-smoothed with an
undocumented filter, and ``a`` in particular is noisy enough that naive "max deceleration"
features mostly measure noise. Every movement-quality claim in this project is therefore
built from the raw ``(t, x, y)`` trajectory with an explicit, reported filter, and the
vendor columns are kept only as a cross-check.

Conventions
-----------
* Positions are yards, ``x`` along the field length (0-120), ``y`` across (0-53.33).
* Time is a uniform 10 Hz grid; :func:`to_uniform_grid` enforces that and reports gaps.
* ``dir`` / ``o`` are degrees. The Big Data Bowl convention is 0 deg = +y, 90 deg = +x,
  i.e. ``vx = s*sin(dir)``, ``vy = s*cos(dir)``. :func:`check_direction_convention`
  verifies this empirically against finite differences -- run it once per dataset before
  trusting any angle-derived feature.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import butter, filtfilt, savgol_filter

from .config import DT, SAMPLE_HZ

__all__ = [
    "to_uniform_grid",
    "smooth_xy",
    "derivatives",
    "Kinematics",
    "curvature",
    "tangential_normal_accel",
    "heading",
    "unwrap_heading",
    "detect_cuts",
    "Cut",
    "sprint_profile",
    "SprintProfile",
    "check_direction_convention",
    "dir_to_velocity",
]


# ======================================================================================
# Grid / resampling
# ======================================================================================

def to_uniform_grid(
    t: np.ndarray,
    *series: np.ndarray,
    dt: float = DT,
    max_gap_frames: int = 3,
) -> tuple[np.ndarray, list[np.ndarray], dict]:
    """Project ``series`` onto a uniform ``dt`` grid spanning ``t``.

    Tracking frames are nominally every 0.100 s but real exports drop frames. Linear
    interpolation across a *short* gap is harmless; across a long one it invents motion.

    Returns ``(t_grid, [resampled...], report)`` where ``report`` records the gap
    structure so that a caller can discard an attempt instead of silently modelling
    interpolated frames.
    """
    t = np.asarray(t, dtype=float)
    if t.ndim != 1 or t.size < 2:
        raise ValueError("need at least two frames")
    order = np.argsort(t)
    t = t[order]
    series = tuple(np.asarray(s, dtype=float)[order] for s in series)

    steps = np.diff(t)
    gap_frames = np.round(steps / dt).astype(int)
    report = {
        "n_frames_in": int(t.size),
        "duration_s": float(t[-1] - t[0]),
        "median_step_s": float(np.median(steps)),
        "n_gaps": int((gap_frames > 1).sum()),
        "max_gap_frames": int(gap_frames.max()) if gap_frames.size else 1,
        "gap_ok": bool(gap_frames.max() <= max_gap_frames) if gap_frames.size else True,
    }

    n = int(round((t[-1] - t[0]) / dt)) + 1
    t_grid = t[0] + np.arange(n) * dt
    out = [np.interp(t_grid, t, s) for s in series]
    report["n_frames_out"] = n
    return t_grid, out, report


# ======================================================================================
# Smoothing and differentiation
# ======================================================================================

def smooth_xy(
    x: np.ndarray,
    y: np.ndarray,
    *,
    method: str = "butter",
    cutoff_hz: float = 2.0,
    order: int = 2,
    savgol_window: int = 11,
    savgol_poly: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Low-pass the position trace before differentiating.

    ``cutoff_hz=2.0`` is a conventional choice for human locomotion: voluntary whole-body
    movement lives below ~2 Hz and a 10 Hz sampler gives a 5 Hz Nyquist, so a 2 Hz
    4th-order zero-phase Butterworth keeps the signal and kills the jitter. Report the
    cutoff in the writeup -- it is a real analytic choice, not a detail.

    ``method="savgol"`` is the alternative: it preserves peak amplitude better (useful if
    you care about *peak* deceleration) at the cost of less stopband rejection.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = x.size

    if method == "none":
        return x, y

    if method == "savgol":
        w = min(savgol_window, n if n % 2 else n - 1)
        if w < savgol_poly + 2:
            return x, y
        return (
            savgol_filter(x, w, savgol_poly),
            savgol_filter(y, w, savgol_poly),
        )

    if method == "butter":
        # filtfilt needs > 3*order padding on each side
        if n <= 3 * (order * 2) + 1:
            return x, y
        wn = cutoff_hz / (SAMPLE_HZ / 2.0)
        if not 0 < wn < 1:
            raise ValueError(f"cutoff_hz={cutoff_hz} invalid for {SAMPLE_HZ} Hz sampling")
        b, a = butter(order, wn, btype="low")
        return filtfilt(b, a, x), filtfilt(b, a, y)

    raise ValueError(f"unknown method {method!r}")


@dataclass(frozen=True)
class Kinematics:
    """Per-frame kinematic state derived from a smoothed trajectory."""

    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    vx: np.ndarray
    vy: np.ndarray
    ax: np.ndarray
    ay: np.ndarray
    speed: np.ndarray          #: |v|, yd/s
    accel: np.ndarray          #: |a|, yd/s^2
    a_tan: np.ndarray          #: tangential accel: >0 propulsion, <0 braking
    a_norm: np.ndarray         #: normal (centripetal) accel: the turning component
    kappa: np.ndarray          #: path curvature, 1/yd
    heading: np.ndarray        #: unwrapped heading, radians
    omega: np.ndarray          #: heading rate of change, rad/s
    jerk: np.ndarray           #: |da/dt|, yd/s^3

    def as_dict(self) -> dict[str, np.ndarray]:
        return {k: v for k, v in asdict(self).items()}


def derivatives(
    t: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    smooth: str = "butter",
    cutoff_hz: float = 2.0,
) -> Kinematics:
    """Full kinematic decomposition of a trajectory.

    The tangential/normal split is the useful one for football. ``a_tan`` is pure
    speed change -- it is what "deceleration into a break" and "burst out of a cut"
    actually mean. ``a_norm`` is the lateral force needed to turn, which is what
    separates a receiver who rounds a route off from one who snaps it.
    """
    t = np.asarray(t, dtype=float)
    xs, ys = smooth_xy(x, y, method=smooth, cutoff_hz=cutoff_hz)

    vx = np.gradient(xs, t, edge_order=2)
    vy = np.gradient(ys, t, edge_order=2)
    ax = np.gradient(vx, t, edge_order=2)
    ay = np.gradient(vy, t, edge_order=2)

    speed = np.hypot(vx, vy)
    accel = np.hypot(ax, ay)
    a_tan, a_norm = tangential_normal_accel(vx, vy, ax, ay)
    kap = curvature(vx, vy, ax, ay)

    hd = unwrap_heading(heading(vx, vy))
    omega = np.gradient(hd, t, edge_order=2)

    jx = np.gradient(ax, t, edge_order=2)
    jy = np.gradient(ay, t, edge_order=2)

    return Kinematics(
        t=t, x=xs, y=ys, vx=vx, vy=vy, ax=ax, ay=ay,
        speed=speed, accel=accel, a_tan=a_tan, a_norm=a_norm,
        kappa=kap, heading=hd, omega=omega, jerk=np.hypot(jx, jy),
    )


def tangential_normal_accel(
    vx: np.ndarray, vy: np.ndarray, ax: np.ndarray, ay: np.ndarray, eps: float = 1e-6
) -> tuple[np.ndarray, np.ndarray]:
    """Split acceleration into along-path (speed change) and across-path (turning)."""
    sp = np.hypot(vx, vy)
    safe = np.maximum(sp, eps)
    a_tan = (vx * ax + vy * ay) / safe
    a_norm = (vx * ay - vy * ax) / safe
    # at a standstill the decomposition is undefined
    a_tan = np.where(sp < eps, 0.0, a_tan)
    a_norm = np.where(sp < eps, 0.0, a_norm)
    return a_tan, a_norm


def curvature(
    vx: np.ndarray, vy: np.ndarray, ax: np.ndarray, ay: np.ndarray, eps: float = 1e-6
) -> np.ndarray:
    """Signed-magnitude path curvature kappa = |v x a| / |v|^3, in 1/yd.

    1/kappa is the instantaneous turn radius. A receiver rounding a 10-yard out at a
    3-yard radius and one cutting at a 1-yard radius have identical 40 times and very
    different separation at the break.
    """
    num = np.abs(vx * ay - vy * ax)
    den = np.power(np.hypot(vx, vy), 3)
    return np.where(den < eps, 0.0, num / np.maximum(den, eps))


def heading(vx: np.ndarray, vy: np.ndarray) -> np.ndarray:
    """Direction of travel in radians, measured as atan2(vy, vx)."""
    return np.arctan2(vy, vx)


def unwrap_heading(h: np.ndarray) -> np.ndarray:
    """Remove 2*pi discontinuities so that heading rate is meaningful."""
    return np.unwrap(h)


# ======================================================================================
# Direction-convention check
# ======================================================================================

def dir_to_velocity(s: np.ndarray, dir_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vendor (s, dir) -> (vx, vy) under the Big Data Bowl convention 0 deg = +y."""
    r = np.deg2rad(np.asarray(dir_deg, dtype=float))
    s = np.asarray(s, dtype=float)
    return s * np.sin(r), s * np.cos(r)


def check_direction_convention(
    t: np.ndarray, x: np.ndarray, y: np.ndarray, s: np.ndarray, dir_deg: np.ndarray,
    *, min_speed: float = 2.0,
) -> dict:
    """Empirically validate the ``dir`` angle convention against finite differences.

    Run this once on real data before building any angle-derived feature. Returns the
    median absolute heading error in degrees under each candidate convention; the
    correct one should be near 0 and the others should not be.
    """
    t = np.asarray(t, float)
    vx_fd = np.gradient(np.asarray(x, float), t, edge_order=2)
    vy_fd = np.gradient(np.asarray(y, float), t, edge_order=2)
    fast = np.hypot(vx_fd, vy_fd) >= min_speed
    if fast.sum() < 5:
        return {"n_frames_used": int(fast.sum()), "verdict": "insufficient motion"}

    h_fd = np.arctan2(vy_fd[fast], vx_fd[fast])
    d = np.deg2rad(np.asarray(dir_deg, float)[fast])

    candidates = {
        "0deg=+y_clockwise": np.arctan2(np.cos(d), np.sin(d)),   # vx=s*sin, vy=s*cos
        "0deg=+x_ccw": d,                                         # vx=s*cos, vy=s*sin
        "0deg=+y_ccw": np.arctan2(np.sin(d), -np.cos(d)),
        "0deg=-y_clockwise": np.arctan2(-np.cos(d), -np.sin(d)),
    }
    errs = {
        name: float(np.rad2deg(np.median(np.abs(np.angle(np.exp(1j * (h - h_fd)))))))
        for name, h in candidates.items()
    }
    best = min(errs, key=errs.get)
    return {
        "n_frames_used": int(fast.sum()),
        "median_abs_error_deg": errs,
        "best": best,
        "verdict": "ok" if errs[best] < 10 else "no convention matches -- investigate",
    }


# ======================================================================================
# Cut detection
# ======================================================================================

@dataclass(frozen=True)
class Cut:
    """One change-of-direction event inside a drill attempt."""

    i_start: int
    i_min: int
    i_end: int
    t_start: float
    t_min: float
    t_end: float
    entry_speed: float          #: peak speed before the cut, yd/s
    min_speed: float            #: speed at the bottom of the cut, yd/s
    exit_speed: float           #: peak speed after the cut, yd/s
    speed_lost: float           #: entry - min
    speed_lost_pct: float       #: fraction of entry speed given up
    heading_change_deg: float   #: total heading swing across the cut
    duration_s: float           #: t_end - t_start, "time in the cut"
    peak_decel: float           #: most negative a_tan in the braking phase (yd/s^2)
    peak_reaccel: float         #: max a_tan in the exit phase (yd/s^2)
    min_turn_radius: float      #: 1/max(kappa) through the cut, yd; nan for a reversal
    recovery_time_s: float      #: time from min_speed back to entry_speed (nan if never)
    is_reversal: bool           #: heading swing >= 150 deg, i.e. a 180 (short shuttle)
    lateral_excursion_yd: float #: max perpendicular distance from the cut's chord

    # Turn radius is undefined for a reversal: when the athlete retraces his own line,
    # velocity and acceleration are parallel, curvature goes to zero and 1/kappa blows
    # up to infinity -- which would read as "the gentlest turn in the dataset" for what
    # is in fact the sharpest. The 5-10-5 short shuttle is built out of exactly this
    # move, so the case is not an edge case here. Reversals report nan for radius and
    # are described by `lateral_excursion_yd` instead: how far off the line the athlete
    # had to drift to get turned around. Smaller is tighter.


def detect_cuts(
    k: Kinematics,
    *,
    min_heading_change_deg: float = 45.0,
    min_speed_drop_frac: float = 0.25,
    min_entry_speed: float = 2.0,
    min_separation_s: float = 0.4,
) -> list[Cut]:
    """Find change-of-direction events from a kinematic trace.

    A cut is a local speed minimum that is both *deep* (the athlete gave up at least
    ``min_speed_drop_frac`` of entry speed) and *directional* (heading swings by at least
    ``min_heading_change_deg`` across it). Requiring both is what separates a genuine
    break from a deceleration in a straight line or a lazy arc at constant speed.

    The returned features are the change-of-direction vocabulary a coach already uses:
    how fast he came in, how much speed he had to dump, how long he spent in the
    transition, and how hard he came out.
    """
    sp = k.speed
    n = sp.size
    if n < 7:
        return []

    # candidate local minima
    cand = [
        i for i in range(2, n - 2)
        if sp[i] <= sp[i - 1] and sp[i] <= sp[i + 1] and sp[i] < sp[i - 2] and sp[i] < sp[i + 2]
    ]

    cuts: list[Cut] = []
    last_t = -np.inf
    for i in cand:
        # walk out to the bracketing speed peaks
        a = i
        while a > 0 and sp[a - 1] >= sp[a]:
            a -= 1
        b = i
        while b < n - 1 and sp[b + 1] >= sp[b]:
            b += 1

        entry, low, exit_ = float(sp[a]), float(sp[i]), float(sp[b])
        if entry < min_entry_speed:
            continue
        drop = (entry - low) / entry if entry > 0 else 0.0
        if drop < min_speed_drop_frac:
            continue

        swing = float(np.rad2deg(abs(k.heading[b] - k.heading[a])))
        if swing < min_heading_change_deg:
            continue
        if k.t[i] - last_t < min_separation_s:
            continue
        last_t = float(k.t[i])

        kap = k.kappa[a:b + 1]
        kmax = float(np.nanmax(kap)) if kap.size else 0.0
        is_rev = swing >= 150.0

        # perpendicular excursion from the straight chord spanning the cut
        px, py = k.x[a:b + 1], k.y[a:b + 1]
        cx, cy = px[-1] - px[0], py[-1] - py[0]
        clen = float(np.hypot(cx, cy))
        if clen > 1e-6:
            lat = float(np.max(np.abs((px - px[0]) * cy - (py - py[0]) * cx) / clen))
        else:
            lat = float(np.max(np.hypot(px - px[0], py - py[0]))) if px.size else np.nan

        # time to get back to entry speed after the low point
        rec = np.nan
        after = np.nonzero(sp[i:] >= entry)[0]
        if after.size:
            rec = float(k.t[i + after[0]] - k.t[i])

        cuts.append(
            Cut(
                i_start=a, i_min=i, i_end=b,
                t_start=float(k.t[a]), t_min=float(k.t[i]), t_end=float(k.t[b]),
                entry_speed=entry, min_speed=low, exit_speed=exit_,
                speed_lost=entry - low, speed_lost_pct=drop,
                heading_change_deg=swing,
                duration_s=float(k.t[b] - k.t[a]),
                peak_decel=float(np.min(k.a_tan[a:i + 1])) if i > a else 0.0,
                peak_reaccel=float(np.max(k.a_tan[i:b + 1])) if b > i else 0.0,
                min_turn_radius=(np.nan if is_rev
                                 else (float(1.0 / kmax) if kmax > 1e-6 else np.inf)),
                recovery_time_s=rec,
                is_reversal=is_rev,
                lateral_excursion_yd=lat,
            )
        )
    return cuts


# ======================================================================================
# Sprint (acceleration) profiling
# ======================================================================================

@dataclass(frozen=True)
class SprintProfile:
    """Mono-exponential sprint-acceleration model fitted to a 40-yard dash trace.

    ``v(t) = vmax * (1 - exp(-t / tau))``

    This is the Samozino/Morin field method for force-velocity profiling. Two athletes
    with the same 40 time can have very different ``(vmax, tau)``: a high-``vmax``,
    high-``tau`` athlete is a long strider who needs runway, a low-``tau`` athlete is
    explosive early. Football cares about that difference far more than about the
    stopwatch, and the distinction is invisible without tracking data.
    """

    vmax: float        #: asymptotic max velocity, yd/s
    tau: float         #: acceleration time constant, s (smaller = more explosive)
    r2: float          #: fit quality
    n_frames: int
    amax: float        #: theoretical initial acceleration vmax/tau, yd/s^2
    f0_rel: float      #: relative max horizontal force proxy = amax (per unit mass)
    pmax_rel: float    #: relative max horizontal power proxy = vmax^2 / (4*tau)
    t_to_10yd: float   #: modelled split, s
    t_to_20yd: float
    t_to_40yd: float
    observed_peak_speed: float
    converged: bool


def _exp_v(t: np.ndarray, vmax: float, tau: float) -> np.ndarray:
    return vmax * (1.0 - np.exp(-t / tau))


def _exp_d(t: np.ndarray, vmax: float, tau: float) -> np.ndarray:
    return vmax * (t + tau * np.exp(-t / tau)) - vmax * tau


def sprint_profile(
    t: np.ndarray, speed: np.ndarray, *, t0: float | None = None
) -> SprintProfile:
    """Fit the mono-exponential velocity model to an acceleration trace.

    ``t0`` lets the caller pass an explicit movement-onset time; otherwise onset is the
    first frame at which speed exceeds 0.3 yd/s, which keeps standing jitter out of the
    fit. The Combine 40 has no reaction-time component (the clock starts on movement),
    so onset detection from the trace is the right definition.
    """
    t = np.asarray(t, float)
    v = np.asarray(speed, float)
    if t0 is None:
        moving = np.nonzero(v > 0.3)[0]
        t0 = float(t[moving[0]]) if moving.size else float(t[0])
    m = t >= t0
    tt, vv = t[m] - t0, v[m]
    if tt.size < 8:
        return SprintProfile(*( [np.nan] * 10 ), n_frames=int(tt.size), converged=False)  # type: ignore[arg-type]

    v_guess = float(np.nanmax(vv))
    try:
        popt, _ = curve_fit(
            _exp_v, tt, vv, p0=[v_guess, 1.0],
            bounds=([0.1, 0.05], [20.0, 10.0]), maxfev=20_000,
        )
        converged = True
    except Exception:
        popt, converged = np.array([v_guess, 1.0]), False

    vmax, tau = float(popt[0]), float(popt[1])
    resid = vv - _exp_v(tt, vmax, tau)
    ss_tot = float(np.sum((vv - vv.mean()) ** 2))
    r2 = float(1 - np.sum(resid ** 2) / ss_tot) if ss_tot > 0 else np.nan

    def _t_at(dist: float) -> float:
        grid = np.linspace(0, 12, 12_001)
        d = _exp_d(grid, vmax, tau)
        hit = np.nonzero(d >= dist)[0]
        return float(grid[hit[0]]) if hit.size else np.nan

    amax = vmax / tau
    return SprintProfile(
        vmax=vmax, tau=tau, r2=r2, n_frames=int(tt.size),
        amax=amax, f0_rel=amax, pmax_rel=vmax * vmax / (4.0 * tau),
        t_to_10yd=_t_at(10.0), t_to_20yd=_t_at(20.0), t_to_40yd=_t_at(40.0),
        observed_peak_speed=float(np.nanmax(vv)), converged=converged,
    )
