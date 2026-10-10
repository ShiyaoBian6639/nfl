"""The NFL side of the linkage: per-player outcome measures from 2023-2025.

Two sources, deliberately kept apart:

``player_play.csv``
    Next Gen Stats per-snap measures. These are the *only* way to get anything
    relational -- separation, cushion, pressure probability -- because the tracking
    files contain no defenders.

``game_tracking_*.csv``
    10 Hz frames for the rookie cohort only. Good for self-referential kinematics
    (how fast did he actually play, how hard did he brake, how tight did he turn)
    and nothing else.

Every aggregate here carries its own denominator. A per-snap rate over 40 snaps and one
over 900 snaps are not the same measurement, and the single fastest way to produce a
nonsense leaderboard in this dataset is to rank on a rate without an exposure column.
"""

from __future__ import annotations

import polars as pl

__all__ = [
    "ROLE_OUTCOMES",
    "receiving_outcomes",
    "pass_block_outcomes",
    "pass_rush_outcomes",
    "frame_kinematics",
    "player_game_speed_profile",
    "attach_exposure",
]


#: Which outcome family applies to which lined-up position. `lined_up_position` is the
#: right key here, not roster position: a TE who aligns in-line on one snap and in the
#: slot on the next is doing two different jobs.
ROLE_OUTCOMES: dict[str, tuple[str, ...]] = {
    "receiving": ("WR", "TE", "RB", "FB"),
    "pass_block": ("T", "G", "C"),
    "pass_rush": ("DE", "DT", "NT", "OLB"),
    "coverage": ("CB", "DB", "FS", "SS", "ILB", "MLB"),
}


def _dropbacks() -> pl.Expr:
    """Every snap on which the QB dropped back.

    Host-specified denominator for pass-rush and pass-protection work: filter
    ``pass_result != ""``. Because the ingest treats the empty string as null, the
    predicate here is "not null".
    """
    return pl.col("pass_result").is_not_null()


# ======================================================================================
# player_play aggregates
# ======================================================================================

def receiving_outcomes(
    player_play: pl.LazyFrame, *, min_routes: int = 25, by_season: bool = False
) -> pl.DataFrame:
    """Separation, cushion and YAC-over-expected per receiver.

    ``separation_at_pass_forward`` is the closest thing in this dataset to a direct
    measurement of route-running success, and it is exactly what a Combine
    change-of-direction metric should predict. ``yac_oe`` is the residual against the
    NGS expected-YAC model, which already conditions on the catch situation -- using the
    residual rather than raw YAC removes most of the scheme and depth confounding.
    """
    keys = ["nfl_id", "season"] if by_season else ["nfl_id"]
    lf = player_play
    if by_season:
        lf = lf.with_columns((pl.col("game_id") // 1_000_000).alias("season"))

    out = (
        lf.filter(pl.col("lined_up_position").is_in(list(ROLE_OUTCOMES["receiving"])))
          .group_by(keys)
          .agg(
              pl.len().alias("snaps"),
              pl.col("route_ran").is_not_null().sum().alias("routes"),
              pl.col("target").sum().alias("targets"),
              pl.col("separation_at_pass_forward").mean().alias("mean_separation"),
              pl.col("separation_at_pass_forward").median().alias("median_separation"),
              pl.col("separation_at_pass_forward").is_not_null().sum().alias("n_separation"),
              pl.col("cushion").mean().alias("mean_cushion"),
              pl.col("rec_yards").sum().alias("rec_yards"),
              pl.col("yards_after_catch").mean().alias("mean_yac"),
              (pl.col("yards_after_catch") - pl.col("expected_yards_after_catch"))
                  .mean().alias("yac_oe"),
              (pl.col("yards_after_catch") - pl.col("expected_yards_after_catch"))
                  .is_not_null().sum().alias("n_yac_oe"),
              pl.col("expected_points_added").mean().alias("epa_per_snap"),
          )
          .filter(pl.col("routes") >= min_routes)
          .sort("routes", descending=True)
    )
    return out.collect()


def pass_block_outcomes(
    player_play: pl.LazyFrame, *, min_dropbacks: int = 50, by_season: bool = False
) -> pl.DataFrame:
    """Pressure and sack rates allowed per offensive lineman.

    Denominator is dropbacks, not snaps: a lineman cannot allow a pressure on a run.
    ``peak_pressure_probability_allowed`` is the more stable measure -- it is continuous
    and does not require the binary pressure event to have occurred, so it reaches a
    usable signal-to-noise ratio in far fewer snaps than pressure rate does.
    """
    keys = ["nfl_id", "season"] if by_season else ["nfl_id"]
    lf = player_play
    if by_season:
        lf = lf.with_columns((pl.col("game_id") // 1_000_000).alias("season"))

    out = (
        lf.filter(pl.col("lined_up_position").is_in(list(ROLE_OUTCOMES["pass_block"])) & _dropbacks())
          .group_by(keys)
          .agg(
              pl.len().alias("dropbacks"),
              pl.col("pressure_allowed").mean().alias("pressure_rate_allowed"),
              pl.col("sack_allowed").sum().alias("sacks_allowed"),
              (pl.col("sack_allowed").sum() / pl.len()).alias("sack_rate_allowed"),
              pl.col("peak_pressure_probability_allowed").mean().alias("mean_peak_pressure_prob"),
              pl.col("time_to_pressure_allowed").mean().alias("mean_time_to_pressure_allowed"),
              pl.col("pass_rushers_encountered").mean().alias("mean_rushers_faced"),
              pl.col("dropback_duration").mean().alias("mean_dropback_duration"),
              pl.col("extended_sack_allowed").sum().alias("extended_sacks_allowed"),
          )
          .filter(pl.col("dropbacks") >= min_dropbacks)
          .sort("dropbacks", descending=True)
    )
    return out.collect()


def pass_rush_outcomes(
    player_play: pl.LazyFrame, *, min_rushes: int = 50, by_season: bool = False
) -> pl.DataFrame:
    """Get-off, pressure rate and time-to-pressure per rusher.

    Null semantics matter here and are easy to get backwards (host-confirmed):
    ``quick_pressure``/``time_to_pressure`` null while rushing means **no pressure**,
    while ``quick_pressure == False`` means a pressure that simply was not quick. So
    "pressured the QB" is ``time_to_pressure.is_not_null()``, *not*
    ``quick_pressure == True``.

    ``player_get_off`` -- time from snap to crossing the line of scrimmage -- is the
    in-game analogue of Combine first-step quickness and the natural response variable
    for any get-off/burst metric built from DL drills.
    """
    keys = ["nfl_id", "season"] if by_season else ["nfl_id"]
    lf = player_play
    if by_season:
        lf = lf.with_columns((pl.col("game_id") // 1_000_000).alias("season"))

    pressured = pl.col("time_to_pressure").is_not_null()
    out = (
        lf.filter(pl.col("lined_up_position").is_in(list(ROLE_OUTCOMES["pass_rush"])) & _dropbacks())
          .group_by(keys)
          .agg(
              pl.len().alias("pass_snaps"),
              pl.col("blitzing").sum().alias("rushes_flagged_blitz"),
              pressured.sum().alias("pressures"),
              pressured.mean().alias("pressure_rate"),
              pl.col("time_to_pressure").mean().alias("mean_time_to_pressure"),
              pl.col("time_to_pressure").min().alias("best_time_to_pressure"),
              (pl.col("quick_pressure") == True).sum().alias("quick_pressures"),  # noqa: E712
              pl.col("player_get_off").mean().alias("mean_get_off"),
              pl.col("player_get_off").quantile(0.10).alias("p10_get_off"),
              pl.col("player_get_off").is_not_null().sum().alias("n_get_off"),
              pl.col("sack").sum().alias("sacks"),
              pl.col("tackle_for_loss").sum().alias("tfl"),
              pl.col("unblocked_pressure").sum().alias("unblocked_pressures"),
          )
          .filter(pl.col("pass_snaps") >= min_rushes)
          .sort("pass_snaps", descending=True)
    )
    return out.collect()


# ======================================================================================
# game tracking kinematics at scale
# ======================================================================================

def frame_kinematics(
    tracking: pl.LazyFrame, *, smooth_frames: int = 5, use_vendor: bool = False
) -> pl.LazyFrame:
    """Vectorised per-frame derivatives over 10 Hz in-game tracking.

    Scale forces a different tool than the Combine side. ``kinematics.derivatives``
    applies a zero-phase Butterworth per attempt, which is right for 6,310 drill reps
    and impossible for ~22.7M game frames in a Python loop. This computes the same
    quantities with polars expressions: a centred rolling mean over ``smooth_frames``
    (5 frames = 0.5 s, a crude low-pass in the same band as the 2 Hz Butterworth)
    followed by central differences.

    The two filters are not identical. When a result depends on the filter -- peak
    deceleration especially -- recompute the subset of interest with
    ``kinematics.derivatives`` and report both. ``use_vendor=True`` skips all of this
    and takes the shipped ``s``/``a`` columns, which is the right cross-check but not
    the right primary measurement.
    """
    grp = ["game_id", "play_id", "nfl_id"]
    lf = tracking.sort(grp + ["time"])

    if use_vendor:
        return lf.with_columns([
            pl.col("s").alias("speed"),
            pl.col("a").alias("accel_vendor"),
        ])

    w = max(3, smooth_frames | 1)  # force odd so the window is centred
    half = w // 2
    # `min_samples=1` would let the window shrink at the edges of a play, which shifts
    # the smoothed position there; differentiating that shift twice manufactures
    # accelerations of tens of yd/s^2 -- an order of magnitude past anything a human
    # produces -- and they land exactly on the per-play extrema that a "peak
    # deceleration" feature reads. Require the full window instead, then drop the
    # frames whose derivatives still straddle a play boundary.
    lf = lf.with_columns([
        pl.col("x").rolling_mean(w, center=True, min_samples=w).over(grp).alias("xs"),
        pl.col("y").rolling_mean(w, center=True, min_samples=w).over(grp).alias("ys"),
        (pl.col("time").diff().over(grp).dt.total_milliseconds() / 1000.0).alias("dt"),
        pl.int_range(pl.len()).over(grp).alias("_i"),
        pl.len().over(grp).alias("_n"),
    ])
    lf = lf.with_columns([
        (pl.col("xs").diff().over(grp) / pl.col("dt")).alias("vx"),
        (pl.col("ys").diff().over(grp) / pl.col("dt")).alias("vy"),
    ])
    lf = lf.with_columns(
        (pl.col("vx").pow(2) + pl.col("vy").pow(2)).sqrt().alias("speed_calc")
    )
    lf = lf.with_columns([
        (pl.col("vx").diff().over(grp) / pl.col("dt")).alias("ax"),
        (pl.col("vy").diff().over(grp) / pl.col("dt")).alias("ay"),
        (pl.col("speed_calc").diff().over(grp) / pl.col("dt")).alias("a_tan_calc"),
    ])
    # two differences on top of a half-window of smoothing: the first `half + 2` and
    # last `half` frames of every play are edge-contaminated
    interior = (pl.col("_i") >= half + 2) & (pl.col("_i") < pl.col("_n") - half)
    return lf.with_columns([
        pl.when(interior).then(pl.col(c)).otherwise(None).alias(c)
        for c in ("vx", "vy", "speed_calc", "ax", "ay", "a_tan_calc")
    ]).drop("_i", "_n")


def player_game_speed_profile(
    tracking: pl.LazyFrame, *, use_vendor: bool = True, min_plays: int = 50
) -> pl.DataFrame:
    """Per-player in-game movement profile: how fast and how hard he actually plays.

    Peak speed is reported as the **p95 of per-play maxima**, not the single career
    maximum. A career max is an extreme-value statistic -- it grows with snap count, so
    ranking on it ranks playing time. The p95 of per-play maxima is stable and
    comparable across very different exposures, and it is the quantity that should be
    regressed on a Combine 40-yard-dash velocity profile.
    """
    grp = ["game_id", "play_id", "nfl_id"]
    lf = frame_kinematics(tracking, use_vendor=use_vendor)
    speed = pl.col("speed") if use_vendor else pl.col("speed_calc")
    acc = pl.col("accel_vendor") if use_vendor else pl.col("a_tan_calc")

    per_play = lf.group_by(grp).agg([
        speed.max().alias("play_peak_speed"),
        acc.max().alias("play_peak_accel"),
        acc.min().alias("play_peak_decel"),
        pl.col("dis").sum().alias("play_distance"),
        pl.len().alias("frames"),
    ])

    return (
        per_play.group_by("nfl_id").agg([
            pl.len().alias("plays_tracked"),
            pl.col("play_peak_speed").quantile(0.95).alias("p95_peak_speed"),
            pl.col("play_peak_speed").quantile(0.90).alias("p90_peak_speed"),
            pl.col("play_peak_speed").max().alias("max_speed_ever"),
            pl.col("play_peak_speed").mean().alias("mean_play_peak_speed"),
            pl.col("play_peak_accel").quantile(0.95).alias("p95_peak_accel"),
            pl.col("play_peak_decel").quantile(0.05).alias("p05_peak_decel"),
            pl.col("play_distance").mean().alias("mean_play_distance"),
        ])
        .filter(pl.col("plays_tracked") >= min_plays)
        .sort("p95_peak_speed", descending=True)
        .collect()
    )


def attach_exposure(df: pl.DataFrame, exposure_col: str, *, label: str = "exposure") -> pl.DataFrame:
    """Flag rows whose denominator is too small to rank on.

    Keeps the row rather than dropping it -- dropping small-sample players is itself a
    selection decision and should be visible in the figure, not hidden in a filter.
    """
    return df.with_columns([
        pl.col(exposure_col).alias(label),
        (pl.col(exposure_col) < pl.col(exposure_col).median() / 4).alias("low_exposure"),
    ])
