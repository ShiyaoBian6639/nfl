# Data dictionary — NFL Big Data Bowl 2027

> Transcribed from the Kaggle Data tab on 2026-10-10, **annotated with forum-confirmed corrections**.
> See `docs/data-quirks.md` for the gotchas. Where the published dictionary and the shipped files
> disagree, **the files win** — that is flagged inline with ⚠️.

9 CSVs, **2.31 GB**, 158 columns, CC BY-NC 4.0.
Cohort: **510 rookie prospects** drafted or signed **2023–2025**, with 10 Hz Combine tracking, 10 Hz in-game
tracking, Next Gen Stats play metrics, and career outcomes.

## The join graph

```
                    players.csv  (510 rows, PK: nfl_id)
                         │
      ┌──────────────────┼───────────────────┬────────────────────────┐
      │                  │                   │                        │
combine_results    combine_tracking   player_career_successes   player_play
  (nfl_id,          (nfl_id,            (nfl_id)                 (game_id, play_id,
   draft_year)       event_id, …)                                  nfl_id)
                                                                       │
                                                      ┌────────────────┴──────────────┐
                                                games.csv              game_tracking_{2023,2024,2025}
                                              (PK: game_id)             (game_id, play_id, nfl_id, time)
```

- Combine side key: `nfl_id` (+ `draft_year`, `event_id`, `attempt`)
- Game side key: `(game_id, play_id, nfl_id)`; tracking adds `time` as the frame key
- `players.nfl_id` is the spine across everything

---

## File 1 — `players.csv` (510 rows)

Demographic, collegiate and draft metadata.

| Column | Type | Example | Notes |
|---|---|---|---|
| `nfl_id` | int64 | 55867 | **Primary key** across all tables |
| `display_name` | str | Will Anderson | |
| `draft_year` | int64 | 2023 | 2023, 2024 or 2025 |
| `nfl_position` | str | DE | WR, CB, T, G, C, DT, DE, OLB, TE, SS, FS, NT, DB, ILB, MLB, RB, FB |
| `birth_date` | str | 2001-09-02 | parse to date; gives **age at Combine** (a known confounder) |
| `college_name` | str | Alabama | |
| `college_conference` | str | Southeastern Conference | |
| `draft_round` | int64/null | 1 | **null ⇒ UDFA** |
| `draft_pick_within_round` | int64/null | 3 | null ⇒ UDFA |
| `draft_overall_pick` | int64/null | 3 | 1–259+; null ⇒ UDFA. **The key confounder.** |

> `nfl_position` (roster position) ≠ `combine_position` (the group they worked out with) ≠
> `lined_up_position` (per-play alignment). Always say which one you mean.

## File 2 — `combine_results.csv`

Official measurements, electronic testing splits, and NGS grades.

| Column | Type | Example | Notes |
|---|---|---|---|
| `draft_year` | int64 | 2023 | |
| `nfl_id` | int64 | 56040 | → players |
| `combine_position` | str | TE | group worked out with |
| `combine_height` | float64 | 77.875 | inches |
| `combine_weight` | int64 | 245 | lbs |
| `hand_size` | float64 | 10.0 | inches |
| `arm_length` | float64 | 32.25 | inches |
| `wing_span` | float64 | 79.75 | inches |
| `ten_yd_split` | float64 | 1.60 | s — electronic |
| `forty` | float64 | 4.84 | s — electronic |
| `vertical` | float64 | 38.5 | inches |
| `broad_jump` | float64 | 125.0 | inches |
| `three_cone` | float64 | 7.12 | s — **null for opt-outs** |
| `short_shuttle` | float64 | 4.25 | s — **null for opt-outs** |
| `bench_reps` | float64 | 22.0 | 225 lb reps — **null for opt-outs** |
| `ngs_athleticism_score` | int64 | 60 | NGS composite, 0–100 percentile |
| `ngs_college_production_score` | float64 | 78.2 | NGS college production |
| `ngs_final_score` | float64 | 74.5 | NGS overall prospect score |

> The three NGS scores are the **incumbent benchmark**. A new metric earns its keep only by adding
> information *on top of* `ngs_athleticism_score` / `ngs_final_score` and the raw drill times.
> Opt-outs are **not missing at random** — healthy, confident, well-positioned prospects skip drills.

## File 3 — `combine_tracking.csv` ⚠️ **463,189 rows**

10 Hz optical tracking over **6,310 drill attempts**.

| Column | Type | Example | Notes |
|---|---|---|---|
| `draft_year` | int64 | 2025 | |
| `event_id` | str | 2025030210… | **unique per continuous drill attempt** — the frame-group key |
| `nfl_id` | int64 | 58286 | ⚠️ dictionary said "null for BALL"; **it is never null**. On BALL rows it is the nfl_id of the athlete performing the drill (host-confirmed). |
| `entity_type` | str | PLAYER | `PLAYER` or `BALL` — **always filter to PLAYER for athlete movement** |
| `time` | str | 2025-03-02T18:56:38.200 | ISO 8601, 0.10 s steps |
| `drill_type` | str | SKILL_DRILLS_OL | FORTY_YARD_DASH, THREE_CONE_DRILL, SHORT_SHUTTLE, SKILL_DRILLS_WR, SKILL_DRILLS_DB, SKILL_DRILLS_OL, SKILL_DRILLS_DL, SKILL_DRILLS_TE |
| `drill_name` | str | OL_PULL_DRILL_FOLD… | GAUNTLET_DRILL, RUN_THE_HOOP_DRILL, BACK_PEDAL_AND_TRANSITION_45_DEGREE_REACTION, SLOT_STRIKE_ROUTE_LEFT, PASS_PRO_MIRROR_DRILL, … |
| `attempt` | int64 | 4 | attempt index within prospect × drill. ⚠️ **Gaps are deliberate**: a missing attempt number means that attempt had a data problem and was dropped (host-confirmed). Two attempts ⇒ **test–retest reliability is computable**. |
| `x` | float64 | 87.09 | yards along field length, 0–120 |
| `y` | float64 | 22.52 | yards across field width, 0–53.33 |
| `s` | float64 | 0.28 | speed, yd/s (vendor-smoothed) |
| `a` | float64 | 0.11 | acceleration, yd/s² (vendor-smoothed) |
| `dis` | float64 | 0.01 | distance since previous frame, yd |
| `dir` | float64 | 126.08 | motion direction, degrees 0–360 |

> **No `o` (orientation) column** in Combine tracking — unlike game tracking. So no "hips vs. feet"
> analysis on the Combine side; direction of travel only.
>
> BALL frames exist in **551 events, only in SKILL_DRILLS_WR and SKILL_DRILLS_TE, covering 54 players**
> (37 WR, 16 TE, 1 FB). Too thin to carry a submission; use as an appendix at most.

## File 4 — `player_career_successes.csv`

Cumulative career outcomes for the 510 prospects.

| Column | Type | Notes |
|---|---|---|
| `nfl_id` | int64 | → players |
| `career_offensive_snaps` | int64 | regular season + playoffs |
| `career_defensive_snaps` | int64 | |
| `career_special_teams_snaps` | int64 | |
| `career_games_active` | int64 | regular-season games on active roster |
| `career_games_started` | int64 | |
| `ap_all_pro_1st_team` | int64 | count of AP 1st-team selections |
| `ap_all_pro_2nd_team` | int64 | count |
| `pro_bowl_original_ballot` | int64 | original-ballot Pro Bowls (alternates excluded) |

> These are **opportunity-contaminated**: snaps and starts are largely a function of draft capital, not
> just ability. Treat them as "did the team give him the job", not "is he good". Use as a *secondary*
> outcome or as a selection model, never as the headline response without adjustment.

## File 5 — `player_play.csv` ⚠️ **314,197 rows**

Per-snap Next Gen Stats for the rookie cohort, 2023–2025 (incl. PRE and POST — host says preseason and
postseason outcomes may be used).

**A. Play context & identifiers** — `game_id`, `play_id`, `team_abbr`, `nfl_id`, `lined_up_position`,
`play_description`, `quarter`, `down`, `yards_to_go`, `possession_team`, `yardline_side`, `yardline_number`,
`game_clock`, `pre_snap_home_score`, `pre_snap_visitor_score`, `play_direction`

**B. Win probability & EPA** — `pre_snap_home_team_win_probability`, `pre_snap_visitor_team_win_probability`,
`home_team_win_probability_added`, `visitor_team_win_probility_added` *(sic — typo is in the data)*,
`expected_points_added`, `expected_points`

**C. Scheme, formation, result** — `offense_formation`, `receiver_alignment`, `pass_result`
(C/I/S/IN/R), `pass_length`, `play_nullified_by_penalty`, `penalty_yards`, `pre_penalty_yards_gained`,
`yards_gained`, `team_coverage_man_zone`, `team_coverage_type`, `in_motion_at_ball_snap`

**D. Receiver / ball carrier** — `target`, `rec_yards`, `rush_yards`, `yards_after_catch`, `fumble`,
`fumble_lost`, `route_ran` (GO/OUT/SLANT/CROSS/POST/CORNER/HITCH/SCREEN/FLAT/WHEEL),
**`separation_at_pass_forward`**, **`cushion`**, `expected_yards_after_catch`

**E. Offensive line / pass protection** — `dropback_duration`, `extended_sack_allowed`,
`pass_rushers_encountered`, **`peak_pressure_probability_allowed`**, `pressure_allowed`, `sack_allowed`,
`time_to_pressure_allowed`

**F. Defensive pass rush / tackling** — `blitzing`, **`player_get_off`**, `sack`, `tackle`, `assist`,
`caused_forced_fumble`, `recovered_fumble`, `tackle_for_loss`, `time_to_pressure`, `time_to_qb_hurry`,
`coverage_assignment`, `coverage_assignment_at_snap`, `quick_pressure`, `unblocked_pressure`

The bolded columns are the **high-value outcome variables** — they are themselves tracking-derived,
continuous, and available per snap, which makes them far better responses than box-score counts.

Null semantics (host-confirmed) — see `docs/data-quirks.md`.

## File 6 — `games.csv` (1,002 games)

`game_id` (YYYYMMDD##, PK), `game_key`, `season` (2023–2025), `season_type` (REG/POST — PRE also appears in
the data), `week` (1–18), `home_team_abbr`, `visitor_team_abbr`.

## Files 7–9 — `game_tracking_{2023,2024,2025}.csv` ⚠️ ~22.7M rows total

10 Hz in-game tracking **for the 510 rookie-cohort players only**.

| Column | Type | Notes |
|---|---|---|
| `game_id`, `play_id`, `nfl_id` | int64 | → player_play |
| `time` | str | ISO 8601, 0.10 s |
| `x`, `y` | float64 | yards; 0–120 × 0–53.33 |
| `s`, `a`, `dis` | float64 | speed yd/s, accel yd/s², per-frame distance |
| `o` | float64 | **body orientation**, degrees — present here, absent at the Combine |
| `dir` | float64 | motion direction, degrees |
| `event` | str/null | ball_snap, pass_forward, pass_arrived, tackle, touchdown, first_contact, out_of_bounds, … |

> 🔴 **The defining structural constraint of this dataset.** In-game tracking contains **only the rookie
> cohort**, not all 22 players. You cannot compute separation, leverage, or defender distance yourself —
> there is no defender in the file. Any "distance to nearest defender" style feature must come from the
> pre-computed `player_play` columns (`separation_at_pass_forward`, `cushion`,
> `peak_pressure_probability_allowed`, …). Build the in-game side around **self-referential kinematics**
> (speed, acceleration, deceleration, curvature, route shape, get-off) joined to NGS-provided context.

### Actual row counts (verified by participants, differ from the Data tab)

| File | Data tab says | Shipped file has |
|---|---:|---:|
| `player_play.csv` | 316,338 | **314,197** |
| `game_tracking_2023.csv` | 1,421,805 | **3,665,443** |
| `game_tracking_2024.csv` | 3,042,118 | **7,827,944** |
| `game_tracking_2025.csv` | 4,339,021 | **11,160,903** |
| `combine_tracking.csv` | — | **463,189** |

Unresolved with the organizers as of 2026-10-10. Verify these yourself on first ingest
(`scripts/00_audit_raw.py`) and record what you find.
