#!/usr/bin/env python
"""Generate a tiny synthetic stand-in for the competition data.

Purpose: develop and test the whole pipeline (ingest -> audit -> features) before the
real 2.3 GB download exists, and keep a fast regression fixture afterwards. The schema
matches the shipped files exactly, and the fixture deliberately reproduces the known
quirks so the audit checks actually fire:

* ``lined_up_position`` contains the literal string ``"NA"``
* some ``attempt`` numbers are missing (attempt 1 dropped, attempt 2 present)
* BALL frames only in ``SKILL_DRILLS_WR`` / ``SKILL_DRILLS_TE``, carrying the athlete id
* 2023/2024 ``x`` quantized to 1/60 yd and ``s`` to 1/300 yd/s; 2025 unquantized
* 2024 back-pedal reps truncated before the break
* a handful of prospects with no in-game snap
* a few tracking keys with no matching ``player_play`` row

    python tests/make_fixtures.py --out data/fixtures
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20270106)

POSITIONS = ["WR", "WR", "TE", "CB", "CB", "FS", "SS", "T", "G", "C", "DE", "DT", "OLB", "RB"]
COMBINE_POS = {"WR": "WR", "TE": "TE", "CB": "DB", "FS": "DB", "SS": "DB",
               "T": "OL", "G": "OL", "C": "OL", "DE": "DL", "DT": "DL",
               "OLB": "DL", "RB": "RB"}
DRILL_TYPE_FOR = {"WR": "SKILL_DRILLS_WR", "TE": "SKILL_DRILLS_TE", "DB": "SKILL_DRILLS_DB",
                  "OL": "SKILL_DRILLS_OL", "DL": "SKILL_DRILLS_DL", "RB": "SKILL_DRILLS_WR"}
SKILL_DRILLS = {
    "SKILL_DRILLS_WR": ["GAUNTLET_DRILL", "SLOT_STRIKE_ROUTE_LEFT"],
    "SKILL_DRILLS_TE": ["GAUNTLET_DRILL", "SLOT_STRIKE_ROUTE_LEFT"],
    "SKILL_DRILLS_DB": ["BACK_PEDAL_AND_TRANSITION_45_DEGREE_REACTION", "W_DRILL"],
    "SKILL_DRILLS_OL": ["PASS_PRO_MIRROR_DRILL", "OL_PULL_DRILL_FOLD_BLOCK"],
    "SKILL_DRILLS_DL": ["RUN_THE_HOOP_DRILL", "BAG_DRILL"],
}


# ----------------------------------------------------------------------------- physics

def sprint_xy(vmax: float, tau: float, dur: float, y0: float, dt: float = 0.1):
    t = np.arange(0, dur + 1e-9, dt)
    x = vmax * (t + tau * np.exp(-t / tau)) - vmax * tau
    y = np.full_like(t, y0) + RNG.normal(0, 0.015, t.size)
    return t, x, y


def l_drill_xy(speed: float, cut_sharpness: float, dur: float, dt: float = 0.1):
    """Crude 3-cone: out 5 yd, back 5, then a 90 deg turn and a loop."""
    t = np.arange(0, dur + 1e-9, dt)
    phase = t / dur
    x = np.where(phase < 0.25, 5 * phase / 0.25,
        np.where(phase < 0.5, 5 - 5 * (phase - 0.25) / 0.25,
        np.where(phase < 0.75, 5 * (phase - 0.5) / 0.25, 5.0)))
    y = np.where(phase < 0.75, 0.0, 5 * (phase - 0.75) / 0.25)
    # sharper cutters round the corners less
    w = max(3, int(round(9 - 6 * cut_sharpness)))
    k = np.ones(w) / w
    x = np.convolve(np.pad(x, (w, w), mode="edge"), k, "same")[w:-w]
    y = np.convolve(np.pad(y, (w, w), mode="edge"), k, "same")[w:-w]
    return t, 40 + x * speed / 7.0, 26.0 + y * speed / 7.0


def backpedal_xy(dur: float, brake: float, dt: float = 0.1):
    """Back-pedal then a 45 deg break. `dur` < ~7 s truncates before the break."""
    t = np.arange(0, dur + 1e-9, dt)
    x, y = [], []
    for ti in t:
        if ti < 5.0:                       # pedal backwards
            x.append(50 - 1.8 * ti)
            y.append(26.0)
        else:                              # plant and drive out at 45 deg
            d = ti - 5.0
            v = brake * d
            x.append(50 - 9.0 + 0.707 * v * d)
            y.append(26.0 + 0.707 * v * d)
    return t, np.array(x), np.array(y)


def quantize(a: np.ndarray, q: float) -> np.ndarray:
    return np.round(a / q) * q


# ------------------------------------------------------------------------------ tables

def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    players, combine, ct_rows = [], [], []
    nfl_id = 55000

    for draft_year in (2023, 2024, 2025):
        for i, pos in enumerate(POSITIONS):
            nfl_id += 1
            cpos = COMBINE_POS[pos]
            # latent athleticism drives both drill traces and (weakly) NFL outcomes
            ath = float(RNG.normal(0, 1))
            drafted = RNG.random() > 0.18
            overall = int(np.clip(RNG.normal(130 - 25 * ath, 60), 1, 259)) if drafted else None

            players.append(dict(
                nfl_id=nfl_id, display_name=f"Player {nfl_id}", draft_year=draft_year,
                nfl_position=pos,
                birth_date=(datetime(2001, 1, 1) + timedelta(days=int(RNG.integers(0, 1400)))).strftime("%Y-%m-%d"),
                college_name=RNG.choice(["Alabama", "Ohio State", "LSU", "Michigan", "Iowa"]),
                college_conference=RNG.choice(["Southeastern Conference", "Big Ten Conference"]),
                draft_round=(overall - 1) // 32 + 1 if overall else None,
                draft_pick_within_round=(overall - 1) % 32 + 1 if overall else None,
                draft_overall_pick=overall,
            ))

            vmax = 9.3 + 0.45 * ath - (0.9 if cpos == "OL" else 0.0)
            tau = 1.25 - 0.09 * ath + (0.18 if cpos == "OL" else 0.0)
            combine.append(dict(
                draft_year=draft_year, nfl_id=nfl_id, combine_position=cpos,
                combine_height=round(float(RNG.normal(74, 2.5)), 3),
                combine_weight=int(RNG.normal(305 if cpos in ("OL", "DL") else 205, 20)),
                hand_size=round(float(RNG.normal(9.5, 0.6)), 2),
                arm_length=round(float(RNG.normal(32.5, 1.3)), 2),
                wing_span=round(float(RNG.normal(78, 3)), 2),
                ten_yd_split=round(1.75 - 0.05 * ath + RNG.normal(0, 0.03), 2),
                forty=round(4.72 - 0.17 * ath + RNG.normal(0, 0.05), 2),
                vertical=round(33 + 2.6 * ath + RNG.normal(0, 1.5), 1),
                broad_jump=round(118 + 6 * ath + RNG.normal(0, 4), 1),
                three_cone=None if RNG.random() < 0.35 else round(7.15 - 0.18 * ath + RNG.normal(0, 0.08), 2),
                short_shuttle=None if RNG.random() < 0.35 else round(4.35 - 0.11 * ath + RNG.normal(0, 0.06), 2),
                bench_reps=None if RNG.random() < 0.30 else float(int(np.clip(RNG.normal(21, 5), 2, 45))),
                ngs_athleticism_score=int(np.clip(50 + 15 * ath + RNG.normal(0, 8), 0, 100)),
                ngs_college_production_score=round(float(np.clip(50 + 14 * ath + RNG.normal(0, 12), 0, 100)), 1),
                ngs_final_score=round(float(np.clip(50 + 15 * ath + RNG.normal(0, 9), 0, 100)), 1),
            ))

            base = datetime(draft_year, 3, 2, 12, 0, 0)
            ev = 0

            def add(tt, xx, yy, dtype, dname, attempt, with_ball=False):
                nonlocal ev
                ev += 1
                eid = f"{draft_year}0302{nfl_id}{ev:03d}"
                vx = np.gradient(xx, tt, edge_order=2)
                vy = np.gradient(yy, tt, edge_order=2)
                s = np.hypot(vx, vy)
                a = np.gradient(s, tt, edge_order=2)
                dis = np.concatenate([[0.0], np.hypot(np.diff(xx), np.diff(yy))])
                dirdeg = (np.degrees(np.arctan2(vx, vy))) % 360  # 0 deg = +y convention
                if draft_year in (2023, 2024):   # the quantized exports
                    xx, yy, s = quantize(xx, 1 / 60), quantize(yy, 1 / 60), quantize(s, 1 / 300)
                for j, ti in enumerate(tt):
                    ct_rows.append(dict(
                        draft_year=draft_year, event_id=eid, nfl_id=nfl_id,
                        entity_type="PLAYER",
                        time=(base + timedelta(seconds=float(ti) + ev * 120)).isoformat(timespec="milliseconds"),
                        drill_type=dtype, drill_name=dname, attempt=attempt,
                        x=round(float(xx[j]), 6), y=round(float(yy[j]), 6),
                        s=round(float(s[j]), 6), a=round(float(a[j]), 3),
                        dis=round(float(dis[j]), 3), dir=round(float(dirdeg[j]), 2),
                    ))
                if with_ball:
                    for j, ti in enumerate(tt[::2]):
                        ct_rows.append(dict(
                            draft_year=draft_year, event_id=eid, nfl_id=nfl_id,  # host: ball carries athlete id
                            entity_type="BALL",
                            time=(base + timedelta(seconds=float(ti) + ev * 120)).isoformat(timespec="milliseconds"),
                            drill_type=dtype, drill_name=dname, attempt=attempt,
                            x=round(float(xx[j * 2]) + 0.4, 3), y=round(float(yy[j * 2]), 3),
                            s=0.0, a=0.0, dis=0.0, dir=0.0,
                        ))

            # 40: sometimes only attempt 2 survives (host: a dropped attempt had a data problem)
            for att in ([2] if RNG.random() < 0.2 else [1, 2][: 1 + (RNG.random() < 0.6)]):
                t_, x_, y_ = sprint_xy(vmax * (1 + RNG.normal(0, 0.012)),
                                       tau * (1 + RNG.normal(0, 0.04)), 5.2, 26.0)
                add(t_, x_ + 40, y_, "FORTY_YARD_DASH", "FORTY_YARD_DASH", att)

            if combine[-1]["three_cone"] is not None:
                t_, x_, y_ = l_drill_xy(vmax * 0.8, 0.5 + 0.2 * ath, 7.2)
                add(t_, x_, y_, "THREE_CONE_DRILL", "THREE_CONE_DRILL", 1)
            if combine[-1]["short_shuttle"] is not None:
                t_, x_, y_ = l_drill_xy(vmax * 0.85, 0.5 + 0.2 * ath, 4.4)
                add(t_, x_, y_, "SHORT_SHUTTLE", "SHORT_SHUTTLE", 1)

            dtype = DRILL_TYPE_FOR[cpos]
            for dname in SKILL_DRILLS[dtype]:
                for att in (1, 2):
                    # per-rep execution noise: without it every reliability estimate is 1.0
                    jitter = float(RNG.normal(0, 0.12))
                    if "BACK_PEDAL" in dname:
                        # the 2024 trap: reps stop before the break
                        dur = 6.0 if draft_year == 2024 else 11.6
                        brake = 0.0 if draft_year == 2024 else max(0.2, 1.4 + 0.3 * ath + jitter)
                        t_, x_, y_ = backpedal_xy(dur, brake)
                    else:
                        t_, x_, y_ = l_drill_xy(vmax * 0.8 * (1 + 0.04 * jitter),
                                                np.clip(0.5 + 0.2 * ath + jitter, 0.05, 0.95), 6.0)
                    add(t_, x_, y_, dtype, dname, att,
                        with_ball=(dtype in ("SKILL_DRILLS_WR", "SKILL_DRILLS_TE") and att == 1))

    pl_df = pd.DataFrame(players)
    pd.DataFrame(combine).to_csv(out / "combine_results.csv", index=False)
    pl_df.to_csv(out / "players.csv", index=False)
    pd.DataFrame(ct_rows).to_csv(out / "combine_tracking.csv", index=False)

    # ---- games
    games = []
    gid = 0
    for season in (2023, 2024, 2025):
        for wk in range(1, 5):
            gid += 1
            games.append(dict(
                game_id=int(f"{season}09{wk:02d}{gid:02d}"), game_key=59000 + gid, season=season,
                season_type="REG", week=wk, home_team_abbr="KC", visitor_team_abbr="BAL"))
    gm = pd.DataFrame(games)
    gm.to_csv(out / "games.csv", index=False)

    # ---- player_play + game_tracking
    # 13-of-510 analogue: a few prospects never reach the field
    never = set(RNG.choice(pl_df.nfl_id.values, size=4, replace=False).tolist())
    pp_rows, gt_rows = [], {2023: [], 2024: [], 2025: []}
    for _, p in pl_df.iterrows():
        if p.nfl_id in never:
            continue
        ath_proxy = -(p.draft_overall_pick or 260) / 260
        for _, g in gm.iterrows():
            if RNG.random() < 0.45:
                continue
            for play in range(int(RNG.integers(3, 8))):
                play_id = 100 + play * 7
                is_pass = RNG.random() < 0.6
                sep = float(np.clip(RNG.normal(2.8 + 1.1 * ath_proxy, 0.9), 0.1, 9))
                pp_rows.append(dict(
                    game_id=g.game_id, play_id=play_id, team_abbr="KC", nfl_id=p.nfl_id,
                    lined_up_position=("NA" if RNG.random() < 0.01 else p.nfl_position),
                    play_description="(12:00) P.Mahomes pass short right",
                    quarter=int(RNG.integers(1, 5)), down=int(RNG.integers(1, 5)),
                    yards_to_go=int(RNG.integers(1, 20)), possession_team="KC",
                    yardline_side="KC", yardline_number=int(RNG.integers(1, 51)),
                    game_clock="12:00", pre_snap_home_score=0, pre_snap_visitor_score=0,
                    play_direction=RNG.choice(["left", "right"]),
                    expected_points_added=round(float(RNG.normal(0, 1.3)), 3),
                    offense_formation=RNG.choice(["SHOTGUN", "SINGLEBACK", "EMPTY", "I_FORM"]),
                    receiver_alignment=RNG.choice(["3x1", "2x2", "3x2"]),
                    pass_result=(RNG.choice(["C", "I", "S", "IN", "R"]) if is_pass else ""),
                    pass_length=round(float(RNG.normal(8, 6)), 1) if is_pass else None,
                    yards_gained=int(RNG.normal(5, 7)),
                    team_coverage_man_zone=RNG.choice(["MAN_COVERAGE", "ZONE_COVERAGE"]),
                    team_coverage_type=RNG.choice(["COVER_1", "COVER_2", "COVER_3", "COVER_6_ZONE"]),
                    target=bool(is_pass and RNG.random() < 0.2),
                    route_ran=RNG.choice(["GO", "OUT", "SLANT", "CROSS", "POST", "HITCH"]) if is_pass else None,
                    separation_at_pass_forward=round(sep, 2) if is_pass else None,
                    cushion=round(float(np.clip(RNG.normal(6, 1.8), 0.5, 12)), 2) if is_pass else None,
                    yards_after_catch=round(float(abs(RNG.normal(4, 3))), 1) if is_pass else None,
                    expected_yards_after_catch=round(float(abs(RNG.normal(4, 2))), 1) if is_pass else None,
                    dropback_duration=round(float(abs(RNG.normal(2.4, 0.6))), 3) if is_pass else None,
                    pressure_allowed=bool(RNG.random() < 0.08),
                    sack_allowed=float(RNG.random() < 0.02),
                    blitzing=bool(RNG.random() < 0.25),
                    # host: NA while blitzing means no pressure; FALSE means a non-quick pressure
                    quick_pressure=(None if RNG.random() < 0.8 else bool(RNG.random() < 0.5)),
                    time_to_pressure=(None if RNG.random() < 0.8 else round(float(RNG.normal(2.6, 0.5)), 2)),
                    player_get_off=(None if RNG.random() < 0.03 else round(float(abs(RNG.normal(0.8, 0.2))), 3)),
                    sack=float(RNG.random() < 0.02), tackle=float(RNG.random() < 0.08),
                    assist=0.0, tackle_for_loss=float(RNG.random() < 0.01),
                    coverage_assignment=RNG.choice(["MAN", "DEEP_THIRD", "FLAT", "HOOK_CURL"]),
                ))
                # tracking frames for this snap
                t_, x_, y_ = sprint_xy(8.5 + RNG.normal(0, 0.6), 1.2, float(RNG.uniform(2.5, 5.0)), float(RNG.uniform(5, 48)))
                vx = np.gradient(x_, t_, edge_order=2); vy = np.gradient(y_, t_, edge_order=2)
                s = np.hypot(vx, vy)
                t0 = datetime(int(g.season), 9, 10, 17, 0, 0)
                for j, ti in enumerate(t_):
                    gt_rows[int(g.season)].append(dict(
                        game_id=g.game_id, play_id=play_id, nfl_id=p.nfl_id,
                        time=(t0 + timedelta(seconds=float(ti) + play * 40)).isoformat(timespec="milliseconds"),
                        x=round(float(x_[j]) + 20, 2), y=round(float(y_[j]), 2),
                        s=round(float(s[j]), 2),
                        a=round(float(np.gradient(s, t_, edge_order=2)[j]), 2),
                        dis=round(float(np.hypot(vx[j], vy[j]) * 0.1), 3),
                        o=round(float(RNG.uniform(0, 360)), 2),
                        dir=round(float(np.degrees(np.arctan2(vx[j], vy[j])) % 360), 2),
                        event=("ball_snap" if j == 0 else ("pass_forward" if j == 12 else None)),
                    ))

    pp = pd.DataFrame(pp_rows)
    # reproduce the join exception: some tracking keys with no player_play row
    drop = pp.sample(n=max(1, len(pp) // 60), random_state=7).index
    pp.drop(index=drop).to_csv(out / "player_play.csv", index=False)
    for season, rows in gt_rows.items():
        pd.DataFrame(rows).to_csv(out / f"game_tracking_{season}.csv", index=False)

    # ---- career successes
    car = []
    for _, p in pl_df.iterrows():
        played = p.nfl_id not in never
        snaps = int(max(0, RNG.normal(1400 - 4 * (p.draft_overall_pick or 260), 500))) if played else 0
        off = p.nfl_position in ("WR", "TE", "T", "G", "C", "RB")
        car.append(dict(
            nfl_id=p.nfl_id,
            career_offensive_snaps=snaps if off else 0,
            career_defensive_snaps=0 if off else snaps,
            career_special_teams_snaps=int(max(0, RNG.normal(200, 150))) if played else 0,
            career_games_active=int(np.clip(snaps / 40, 0, 51)),
            career_games_started=int(np.clip(snaps / 60, 0, 51)),
            ap_all_pro_1st_team=int(RNG.random() < 0.02),
            ap_all_pro_2nd_team=int(RNG.random() < 0.03),
            pro_bowl_original_ballot=int(RNG.random() < 0.05),
        ))
    pd.DataFrame(car).to_csv(out / "player_career_successes.csv", index=False)

    print(f"fixtures -> {out}")
    for f in sorted(out.glob("*.csv")):
        n = sum(1 for _ in f.open()) - 1
        print(f"  {f.name:28s} {n:>9,} rows  {f.stat().st_size/1e6:>6.2f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/fixtures")
    a = ap.parse_args()
    build(Path(a.out))
