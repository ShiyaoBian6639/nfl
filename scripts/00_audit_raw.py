#!/usr/bin/env python
"""Audit the raw competition data and write a reproducible report.

Run this FIRST, before any modelling. It re-derives from the shipped files every claim
in docs/data-quirks.md rather than trusting the forum, and writes
``reports/data_audit.md`` plus supporting CSVs.

    python scripts/00_audit_raw.py            # audit parquet (fast; needs `make parquet`)
    python scripts/00_audit_raw.py --from-csv # audit the CSVs directly

Checks performed
----------------
1.  Row counts vs. the Kaggle Data tab and vs. the counts reported on the forum
2.  Key uniqueness and null keys on every table
3.  Bidirectional join coverage: game_tracking <-> player_play <-> players
4.  Cohort coverage: which of the 510 prospects have Combine tracking / in-game plays
5.  Combine drill inventory: drill x year x position, attempts per prospect
6.  BALL-frame semantics in combine_tracking
7.  Coordinate quantization by draft year (the 2025 export difference)
8.  Back-pedal rep truncation by draft year (the 2024 trap)
9.  The ``dir`` angle convention, validated against finite differences
10. Frame-gap structure inside drill attempts
11. Null semantics on the pass-rush columns
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import polars as pl

from nflbdb import ingest
from nflbdb.config import (
    ADVERTISED_ROWS,
    FILES,
    FORUM_REPORTED_ROWS,
    GAME_TRACKING,
    REPORTS,
    RAW,
)
from nflbdb.kinematics import check_direction_convention

OUT_MD = REPORTS / "data_audit.md"
OUT_DIR = REPORTS / "audit"
OUT_DIR.mkdir(parents=True, exist_ok=True)

_lines: list[str] = []

#: Questions the audit exists to settle, filled in by the checks and rendered as the
#: first section of the report. See docs/plan.md step 1.
DECISIONS: dict[str, dict] = {}


def decide(key: str, question: str, answer: str, detail: str = "", ok: bool | None = None) -> None:
    DECISIONS[key] = {"q": question, "a": answer, "detail": detail, "ok": ok}


def emit(s: str = "") -> None:
    print(s)
    _lines.append(s)


def h(level: int, text: str) -> None:
    emit()
    emit("#" * level + " " + text)
    emit()


def table(df: pl.DataFrame, max_rows: int = 40) -> None:
    """Emit a polars frame as a markdown table."""
    d = df.head(max_rows)
    cols = d.columns
    emit("| " + " | ".join(cols) + " |")
    emit("|" + "|".join(["---"] * len(cols)) + "|")
    def _fmt(v):
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:,.4g}"
        if isinstance(v, bool):
            return str(v)
        if isinstance(v, int):
            return f"{v:,}" if abs(v) >= 10_000 else str(v)
        return str(v)

    for row in d.iter_rows():
        emit("| " + " | ".join(_fmt(v) for v in row) + " |")
    if df.height > max_rows:
        emit(f"\n*({df.height - max_rows} more rows omitted)*")


def _scan(name: str, from_csv: bool) -> pl.LazyFrame:
    if from_csv:
        return pl.scan_csv(ingest.csv_path(name), null_values=[""], infer_schema_length=50_000)
    return ingest.scan(name)


# ======================================================================================

def check_row_counts(from_csv: bool) -> None:
    h(2, "1. Row counts")
    rows = []
    for name in FILES:
        try:
            n = _scan(name, from_csv).select(pl.len()).collect().item()
        except FileNotFoundError:
            rows.append({"table": name, "actual": None, "data_tab": ADVERTISED_ROWS.get(name),
                         "forum": FORUM_REPORTED_ROWS.get(name), "note": "FILE MISSING"})
            continue
        adv = ADVERTISED_ROWS.get(name)
        forum = FORUM_REPORTED_ROWS.get(name)
        note = []
        if adv is not None:
            note.append("data-tab MATCH" if adv == n else f"data-tab OFF by {n - adv:+,}")
        if forum is not None:
            note.append("forum MATCH" if forum == n else f"forum OFF by {n - forum:+,}")
        rows.append({"table": name, "actual": n, "data_tab": adv, "forum": forum,
                     "note": "; ".join(note) or "-"})
    table(pl.DataFrame(rows))


def check_keys(from_csv: bool) -> None:
    h(2, "2. Key integrity")
    specs = {
        "players": ["nfl_id"],
        "combine_results": ["nfl_id"],
        "games": ["game_id"],
        "player_career_successes": ["nfl_id"],
        "player_play": ["game_id", "play_id", "nfl_id"],
        "combine_tracking": ["event_id", "entity_type", "time"],
    }
    rows = []
    for name, keys in specs.items():
        try:
            lf = _scan(name, from_csv)
        except FileNotFoundError:
            continue
        df = lf.select(keys).collect()
        rows.append({
            "table": name,
            "key": "+".join(keys),
            "rows": df.height,
            "distinct": df.n_unique(),
            "dupes": df.height - df.n_unique(),
            "null_keys": int(df.null_count().sum_horizontal().item()),
        })
    for name in GAME_TRACKING:
        try:
            df = _scan(name, from_csv).select(["game_id", "play_id", "nfl_id", "time"]).collect()
        except FileNotFoundError:
            continue
        rows.append({
            "table": name, "key": "game_id+play_id+nfl_id+time",
            "rows": df.height, "distinct": df.n_unique(),
            "dupes": df.height - df.n_unique(),
            "null_keys": int(df.null_count().sum_horizontal().item()),
        })
    table(pl.DataFrame(rows))


def check_joins(from_csv: bool) -> None:
    h(2, "3. Join coverage (tracking <-> player_play)")
    try:
        pp = _scan("player_play", from_csv).select(["game_id", "play_id", "nfl_id"]).unique().collect()
    except FileNotFoundError:
        emit("_player_play missing_")
        return

    rows = []
    unmatched_all = []
    for name in GAME_TRACKING:
        try:
            tk = _scan(name, from_csv).select(["game_id", "play_id", "nfl_id"]).unique().collect()
        except FileNotFoundError:
            continue
        season = int(name.split("_")[-1])
        left_only = tk.join(pp, on=["game_id", "play_id", "nfl_id"], how="anti")
        right_only = pp.join(tk, on=["game_id", "play_id", "nfl_id"], how="anti")
        rows.append({
            "season": season,
            "tracking_keys": tk.height,
            "tracking_without_player_play": left_only.height,
            "player_play_without_tracking_in_season": right_only.height,
        })
        unmatched_all.append(left_only.with_columns(pl.lit(season).alias("season")))

    table(pl.DataFrame(rows))
    emit()
    emit("> Forum report (discussion/747584): tracking-without-player_play 449 / 857 / 1,191 "
         "(total 2,497); concentrated in WR (1,760), TE (721), FB (16).")

    if unmatched_all:
        um = pl.concat(unmatched_all)
        try:
            players = _scan("players", from_csv).select(["nfl_id", "nfl_position"]).collect()
            by_pos = (um.join(players, on="nfl_id", how="left")
                        .group_by("nfl_position").len().sort("len", descending=True))
            h(3, "Unmatched tracking keys by roster position")
            table(by_pos)
        except FileNotFoundError:
            pass
        um.write_csv(OUT_DIR / "unmatched_tracking_keys.csv")
        emit(f"\n_Exception table written to `{OUT_DIR / 'unmatched_tracking_keys.csv'}`._")


def check_cohort(from_csv: bool) -> None:
    h(2, "4. Cohort coverage")
    players = _scan("players", from_csv).collect()
    emit(f"- `players.csv`: **{players.height}** prospects, "
         f"{players['draft_year'].n_unique()} draft years")

    have_ct = (_scan("combine_tracking", from_csv)
               .filter(pl.col("entity_type") == "PLAYER")
               .select("nfl_id").unique().collect())
    have_pp = _scan("player_play", from_csv).select("nfl_id").unique().collect()

    emit(f"- with Combine tracking: **{have_ct.height}**")
    emit(f"- with any in-game play: **{have_pp.height}** "
         f"(host: 13 of 510 never reached the field)")

    pos_counts = players.group_by("nfl_position").len().sort("len", descending=True)
    has_qb = "QB" in players["nfl_position"].to_list()
    decide("qb_present", "Are there any quarterbacks in the cohort?",
           "yes" if has_qb else "**no**",
           "The documented position list omits QB. If confirmed, QB-centric public work "
           "(nfelo QB rankings and similar) does not transfer as a data source.",
           ok=not has_qb)
    decide("position_counts", "Real sample size per position group",
           ", ".join(f"{r[0]} {r[1]}" for r in pos_counts.rows()[:12]),
           "Every sample-size estimate in docs/research-brief.md is unverified until this line.")

    never = players.join(have_pp, on="nfl_id", how="anti")
    h(3, f"The {never.height} prospects with no NFL snap")
    table(never.select(["nfl_id", "display_name", "draft_year", "nfl_position",
                        "draft_round", "draft_overall_pick"])
               .sort(["draft_year", "draft_overall_pick"], nulls_last=True))
    emit()
    emit("> Host: *\"the 13 players who do not have in-game record did not ever make it to the "
         "field. You could use this information as part of your analysis.\"* These are the only "
         "fully censored observations in the cohort.")

    h(3, "Cohort by draft year x position group")
    piv = (players.group_by(["draft_year", "nfl_position"]).len()
                  .pivot(on="draft_year", index="nfl_position", values="len")
                  .sort("nfl_position"))
    table(piv.select(["nfl_position"] + sorted(c for c in piv.columns if c != "nfl_position")),
          max_rows=40)


def check_drills(from_csv: bool) -> None:
    h(2, "5. Combine drill inventory")
    ct = (_scan("combine_tracking", from_csv)
          .filter(pl.col("entity_type") == "PLAYER")
          .select(["draft_year", "event_id", "nfl_id", "drill_type", "drill_name", "attempt"])
          .unique()
          .collect())

    emit(f"- distinct drill attempts (`event_id`): **{ct['event_id'].n_unique():,}** "
         f"(data tab says 6,310)")

    h(3, "Attempts by drill_type x draft_year")
    table(ct.group_by(["drill_type", "draft_year"]).agg(
        pl.col("event_id").n_unique().alias("attempts"),
        pl.col("nfl_id").n_unique().alias("players"),
    ).pivot(on="draft_year", index="drill_type", values="attempts").sort("drill_type"))

    h(3, "Attempts by drill_name (all years)")
    table(ct.group_by("drill_name").agg(
        pl.col("event_id").n_unique().alias("attempts"),
        pl.col("nfl_id").n_unique().alias("players"),
        pl.col("attempt").max().alias("max_attempt"),
    ).sort("attempts", descending=True), max_rows=60)

    h(3, "Reps per prospect per drill (test-retest feasibility)")
    reps = (ct.group_by(["drill_name", "nfl_id"]).agg(pl.col("event_id").n_unique().alias("n_reps"))
              .group_by(["drill_name", "n_reps"]).len()
              .pivot(on="n_reps", index="drill_name", values="len").sort("drill_name"))
    table(reps, max_rows=60)
    emit()
    emit("> Any drill where a meaningful number of prospects have >= 2 reps supports a "
         "**split-half / test-retest reliability** estimate. A movement metric with no "
         "reported reliability will not survive a judge who works in an NFL analytics "
         "department -- this table decides which drills can carry a metric.")


def check_ball_frames(from_csv: bool) -> None:
    h(2, "6. BALL-frame semantics")
    ct = _scan("combine_tracking", from_csv).select(
        ["event_id", "nfl_id", "entity_type", "drill_type", "drill_name"]
    ).collect()
    n_null = int(ct["nfl_id"].null_count())
    emit(f"- null `nfl_id` rows across the whole file: **{n_null}** "
         f"(dictionary originally claimed null on BALL rows; host corrected it)")

    ball = ct.filter(pl.col("entity_type") == "BALL")
    emit(f"- BALL rows: **{ball.height:,}** in **{ball['event_id'].n_unique():,}** events, "
         f"**{ball['nfl_id'].n_unique()}** distinct players")
    if ball.height:
        h(3, "BALL coverage by drill_type")
        table(ball.group_by("drill_type").agg(
            pl.col("event_id").n_unique().alias("events"),
            pl.col("nfl_id").n_unique().alias("players"),
        ).sort("events", descending=True))

        # does the BALL nfl_id always equal the PLAYER nfl_id in the same event?
        per_event = ct.group_by("event_id").agg(
            pl.col("nfl_id").filter(pl.col("entity_type") == "PLAYER").unique().alias("p"),
            pl.col("nfl_id").filter(pl.col("entity_type") == "BALL").unique().alias("b"),
        ).filter(pl.col("b").list.len() > 0)
        same = per_event.filter(pl.col("p").list.sort() == pl.col("b").list.sort()).height
        emit(f"\n- events where BALL `nfl_id` == PLAYER `nfl_id`: "
             f"**{same}/{per_event.height}** (host: BALL rows carry the drilling athlete's id)")

        g = ball.filter(pl.col("drill_name").cast(pl.Utf8).str.contains("GAUNTLET"))
        n_g = g["nfl_id"].n_unique()
        decide("gauntlet_ball", "How many prospects have ball tracking in the gauntlet?",
               f"{n_g} players, {g['event_id'].n_unique()} events",
               "Research question 'speed retention through the catch' needs roughly 40+ "
               "to carry a submission; below that it is an appendix figure.",
               ok=n_g >= 40)
    else:
        decide("gauntlet_ball", "How many prospects have ball tracking in the gauntlet?",
               "none found", "", ok=False)


def check_quantization(from_csv: bool) -> None:
    h(2, "7. Coordinate quantization by draft year")
    emit("Forum claim: 2023/2024 `x` lies on a 1/60-yard grid and `s` on a 1/300 yd/s grid for "
         "100% of frames; 2025 is a different, unquantized export.")
    emit()
    ct = (_scan("combine_tracking", from_csv)
          .filter(pl.col("entity_type") == "PLAYER")
          .select(["draft_year", "x", "y", "s"])
          .collect())
    rows = []
    for yr in sorted(ct["draft_year"].unique().to_list()):
        d = ct.filter(pl.col("draft_year") == yr)
        for col, q in (("x", 1 / 60), ("y", 1 / 60), ("s", 1 / 300)):
            v = d[col].drop_nulls().to_numpy()
            if v.size == 0:
                continue
            resid = np.abs(v / q - np.round(v / q))
            rows.append({
                "draft_year": yr, "column": col, "quantum": round(q, 6),
                "frac_on_grid": round(float((resid < 1e-6).mean()), 4),
                "n_frames": int(v.size),
            })
    table(pl.DataFrame(rows))

    h(3, "Peak speed in DB drills by year (export-shift sanity check)")
    db = (_scan("combine_tracking", from_csv)
          .filter((pl.col("entity_type") == "PLAYER") & (pl.col("drill_type") == "SKILL_DRILLS_DB"))
          .group_by(["draft_year", "event_id"]).agg(pl.col("s").max().alias("peak_s"))
          .group_by("draft_year").agg(
              pl.col("peak_s").median().alias("median_peak_s"),
              pl.len().alias("attempts"))
          .sort("draft_year").collect())
    table(db)
    emit()
    emit("> If the year effect is real, **standardize every drill metric within "
         "`(drill_name, draft_year)`** before comparing prospects across classes -- and fit "
         "that centering on training folds only, or leave-one-draft-class-out CV silently "
         "becomes transductive.")


def check_backpedal(from_csv: bool) -> None:
    h(2, "8. Back-pedal rep truncation (the 2024 trap)")
    emit("Forum claim: 2024 `BACK_PEDAL_AND_TRANSITION_45_DEGREE_REACTION` reps stop before the "
         "break -- median rep 6.0 s (2024) vs 11.6 s (2023), median max deceleration 0.01 vs "
         "3.6 yd/s^2.")
    emit()
    bp = (_scan("combine_tracking", from_csv)
          .filter((pl.col("entity_type") == "PLAYER")
                  & (pl.col("drill_name").cast(pl.Utf8).str.contains("BACK_PEDAL")))
          .select(["draft_year", "drill_name", "event_id", "time", "s", "a"])
          .collect())
    if bp.is_empty():
        emit("_no BACK_PEDAL drills found_")
        return
    per_rep = bp.group_by(["drill_name", "draft_year", "event_id"]).agg(
        ((pl.col("time").max() - pl.col("time").min()).dt.total_milliseconds() / 1000).alias("dur_s"),
        pl.col("s").max().alias("peak_s"),
        pl.col("a").min().alias("min_a"),
        pl.len().alias("frames"),
    )
    table(per_rep.group_by(["drill_name", "draft_year"]).agg(
        pl.len().alias("reps"),
        pl.col("dur_s").median().round(2).alias("median_dur_s"),
        pl.col("frames").median().alias("median_frames"),
        pl.col("peak_s").median().round(2).alias("median_peak_s"),
        pl.col("min_a").median().round(2).alias("median_min_a"),
    ).sort(["drill_name", "draft_year"]), max_rows=40)

    byyr = per_rep.group_by("draft_year").agg(pl.col("dur_s").median().alias("m")).sort("draft_year")
    if byyr.height >= 2:
        ms = dict(zip(byyr["draft_year"].to_list(), byyr["m"].to_list()))
        other = [v for k, v in ms.items() if k != 2024 and v is not None]
        trunc = (2024 in ms and ms[2024] is not None and other
                 and ms[2024] < 0.75 * (sum(other) / len(other)))
        decide("backpedal_2024", "Is the 2024 back-pedal truncation real?",
               "**yes**" if trunc else "no",
               "median rep duration by year: "
               + ", ".join(f"{k} {v:.1f}s" for k, v in ms.items() if v is not None)
               + (". Idea 'transition tax' runs on two draft classes, not three."
                  if trunc else ""),
               ok=not trunc)

    emit()
    emit("> A truncated phase cannot be repaired by centering. If 2024 is confirmed truncated, "
         "either drop that drill-year or restrict to a complete-phase subset, and report the "
         "sensitivity of every conclusion to that choice.")


def check_dir_convention(from_csv: bool) -> None:
    h(2, "9. `dir` angle convention")
    ct = (_scan("combine_tracking", from_csv)
          .filter((pl.col("entity_type") == "PLAYER") & (pl.col("drill_type") == "FORTY_YARD_DASH"))
          .select(["event_id", "time", "x", "y", "s", "dir"])
          .collect())
    if ct.is_empty():
        emit("_no 40-yard-dash frames_")
        return
    results = []
    for eid in ct["event_id"].unique().to_list()[:40]:
        d = ct.filter(pl.col("event_id") == eid).sort("time")
        t = d["time"].dt.timestamp("ms").to_numpy() / 1000.0
        r = check_direction_convention(t, d["x"].to_numpy(), d["y"].to_numpy(),
                                       d["s"].to_numpy(), d["dir"].to_numpy())
        if "median_abs_error_deg" in r:
            results.append(r["median_abs_error_deg"])
    if not results:
        emit("_insufficient motion to test_")
        return
    agg = {k: round(float(np.median([r[k] for r in results])), 2) for k in results[0]}
    table(pl.DataFrame([{"convention": k, "median_abs_heading_error_deg": v}
                        for k, v in sorted(agg.items(), key=lambda kv: kv[1])]))
    emit()
    emit(f"- tested on **{len(results)}** 40-yard-dash attempts")
    best = min(agg, key=agg.get)
    decide("dir_convention", "Which `dir` angle convention does the data use?",
           f"`{best}` ({agg[best]}° median error)",
           "Lock this in before building any angle-derived feature.",
           ok=agg[best] < 10)
    emit("> The winning convention should be near 0 deg and the others clearly worse. "
         "Lock it in before building any angle-derived feature.")


def check_frame_gaps(from_csv: bool) -> None:
    h(2, "10. Frame-gap structure inside drill attempts")
    ct = (_scan("combine_tracking", from_csv)
          .filter(pl.col("entity_type") == "PLAYER")
          .select(["drill_type", "event_id", "time"])
          .collect()
          .sort(["event_id", "time"]))
    g = ct.with_columns(
        (pl.col("time").diff().over("event_id").dt.total_milliseconds() / 1000.0).alias("dt")
    ).drop_nulls("dt")
    table(g.group_by("drill_type").agg(
        pl.col("dt").median().round(3).alias("median_dt_s"),
        pl.col("dt").quantile(0.99).round(3).alias("p99_dt_s"),
        pl.col("dt").max().round(2).alias("max_dt_s"),
        (pl.col("dt") > 0.15).mean().round(5).alias("frac_gapped"),
    ).sort("drill_type"))


def check_forty_fidelity(from_csv: bool) -> None:
    h(2, "12. Tracked 40 time vs the official clock, and the `dis` under-count")
    emit("Reported elsewhere: a 40 reconstructed from tracking runs ~0.3 s slower than the "
         "official electronic time (correlated ~0.91), and `dis` sums to ~37 yd over a "
         "40-yard dash. Both change how results can be presented.")
    emit()
    ct = (_scan("combine_tracking", from_csv)
          .filter((pl.col("entity_type") == "PLAYER")
                  & (pl.col("drill_type") == "FORTY_YARD_DASH"))
          .select(["nfl_id", "event_id", "time", "x", "y", "s", "dis"])
          .collect().sort(["event_id", "time"]))
    if ct.is_empty():
        emit("_no 40-yard-dash frames_")
        return

    rows = []
    for eid, g in ct.partition_by("event_id", as_dict=True).items():
        t = g["time"].dt.timestamp("ms").to_numpy() / 1000.0
        x, y = g["x"].to_numpy(), g["y"].to_numpy()
        step = np.hypot(np.diff(x), np.diff(y))
        path = float(step.sum())
        moving = np.nonzero(g["s"].to_numpy() > 0.3)[0]
        t0 = t[moving[0]] if moving.size else t[0]
        cum = np.concatenate([[0.0], np.cumsum(step)])
        hit = np.nonzero(cum >= 40.0)[0]
        t40 = float(t[hit[0]] - t0) if hit.size else np.nan
        rows.append({"nfl_id": g["nfl_id"][0], "tracked_40": t40,
                     "path_len": path, "dis_sum": float(g["dis"].sum())})
    d = pl.DataFrame(rows).group_by("nfl_id").agg(
        pl.col("tracked_40").min(), pl.col("path_len").max(), pl.col("dis_sum").max())

    cr = _scan("combine_results", from_csv).select(["nfl_id", "forty"]).collect()
    j = d.join(cr, on="nfl_id", how="inner").drop_nulls(["tracked_40", "forty"])
    j = j.filter(pl.col("tracked_40").is_finite())
    if j.height >= 3:
        diff = (j["tracked_40"] - j["forty"]).to_numpy()
        r = float(np.corrcoef(j["tracked_40"].to_numpy(), j["forty"].to_numpy())[0, 1])
        table(pl.DataFrame([{
            "n_players": j.height,
            "median_tracked_minus_official_s": round(float(np.median(diff)), 3),
            "mean_diff_s": round(float(np.mean(diff)), 3),
            "corr_tracked_vs_official": round(r, 3),
        }]))
        decide("forty_offset",
               "Do tracking-derived 40 times run slow vs the official clock?",
               f"median offset {np.median(diff):+.2f} s (corr {r:.2f}, n={j.height})",
               "Never present a tracking-derived time as 'the 40'.")
    else:
        decide("forty_offset",
               "Do tracking-derived 40 times run slow vs the official clock?",
               "not computable",
               "Fewer than 3 attempts reach a 40-yard cumulative path — check whether the "
               "tracked window ends before the finish line.", ok=False)
    emit()
    h(3, "`dis` as a distance measure")
    ratio = (j["dis_sum"] / j["path_len"]).drop_nulls() if "dis_sum" in j.columns else None
    tbl = d.select([
        pl.col("path_len").median().round(2).alias("median_integrated_path_yd"),
        pl.col("dis_sum").median().round(2).alias("median_sum_of_dis_yd"),
        (pl.col("dis_sum") / pl.col("path_len")).median().round(4).alias("dis_over_path"),
    ])
    table(tbl)
    rr = float(tbl["dis_over_path"][0])
    decide("dis_reliable", "Is `dis` usable as a distance measure?",
           ("no" if abs(rr - 1) > 0.02 else "yes"),
           f"sum(dis) / integrated path = {rr:.3f} over a 40-yard dash")


def check_pass_rush_nulls(from_csv: bool) -> None:
    h(2, "11. Pass-rush null semantics")
    emit("Host: `quick_pressure`/`time_to_pressure` **NA while `blitzing` is TRUE means no "
         "pressure**; `quick_pressure == FALSE` means a pressure happened but was not quick. "
         "`player_get_off` is NA if the rusher never crossed the line of scrimmage. The "
         "denominator of pass-rush opportunities is `pass_result != \"\"`.")
    emit()
    cols = ["blitzing", "quick_pressure", "time_to_pressure", "player_get_off", "sack",
            "pass_result"]
    pp = _scan("player_play", from_csv)
    have = [c for c in cols if c in pp.collect_schema().names()]
    d = pp.select(have).collect()
    rows = [{"column": c, "nulls": int(d[c].null_count()),
             "null_pct": round(100 * d[c].null_count() / d.height, 2),
             "distinct": d[c].n_unique()} for c in have]
    table(pl.DataFrame(rows))
    if {"blitzing", "quick_pressure"} <= set(have):
        h(3, "`blitzing` x `quick_pressure` cross-tab (should confirm the host's reading)")
        table(d.group_by(["blitzing", "quick_pressure"]).len().sort("len", descending=True))


# ======================================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-csv", action="store_true",
                    help="read the raw CSVs instead of the parquet mirrors")
    args = ap.parse_args()

    if not any(RAW.glob("*.csv")):
        print(f"No CSVs in {RAW}. See README -> 'Getting the data'.", file=sys.stderr)
        return 1

    emit("# Data audit — NFL Big Data Bowl 2027")
    emit()
    emit("Generated by `scripts/00_audit_raw.py`. Every number here is derived from the shipped "
         "files; forum claims are quoted alongside so the two can be compared directly.")

    for fn in (check_row_counts, check_keys, check_joins, check_cohort, check_drills,
               check_ball_frames, check_quantization, check_backpedal,
               check_dir_convention, check_frame_gaps, check_pass_rush_nulls,
               check_forty_fidelity):
        try:
            fn(args.from_csv)
        except Exception as exc:  # keep auditing even if one check fails
            h(2, f"{fn.__name__} — FAILED")
            emit(f"```\n{type(exc).__name__}: {exc}\n```")

    # the decisions block is written first but can only be filled in last
    head = ["# Data audit — NFL Big Data Bowl 2027", "",
            "Generated by `scripts/00_audit_raw.py`. Every number is derived from the "
            "shipped files; forum claims are quoted alongside so the two can be compared.",
            "", "## Decisions this audit settles", "",
            "See `docs/plan.md` step 1. These are the questions that determine which "
            "research question is viable.", "",
            "| Question | Answer | What it means |", "|---|---|---|"]
    for v in DECISIONS.values():
        mark = "" if v["ok"] is None else ("✅ " if v["ok"] else "⚠️ ")
        head.append(f"| {v['q']} | {mark}{v['a']} | {v['detail']} |")
    if not DECISIONS:
        head.append("| _no checks reported a decision_ | | |")
    head.append("")
    head.append("---")

    body = _lines[3:] if _lines[:1] == ["# Data audit — NFL Big Data Bowl 2027"] else _lines
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(head + body) + "\n")
    print(f"\nWrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
