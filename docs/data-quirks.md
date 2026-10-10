# Verified against the real data (2026-10-10)

The full dataset is downloaded and audited. Regenerate with `make audit`;
`reports/data_audit.md` carries the detail. Status of every prior claim:

## Confirmed exactly

| Claim | Verified value |
|---|---|
| Shipped row counts differ from the Data tab | **All forum counts exact.** combine_tracking 463,189 · player_play 314,197 · game_tracking 3,665,443 / 7,827,944 / 11,160,903. Total 23,434,208 rows → 394 MB parquet |
| 2024 back-pedal reps are truncated | **Yes.** Median rep duration 2023 **10.9 s** · 2024 **6.1 s** · 2025 **9.7 s** |
| Tracked 40 times run slow | **+0.35 s median offset**, corr **0.91** with the official clock (n = 389) |
| `dis` under-counts distance | **sum(dis) / integrated path = 0.915** (37.09 yd vs 40.67 yd over a 40) |
| `dir` convention is 0° = +y, clockwise | **Yes**, 0.23° median heading error; every alternative ≥ 90° |
| `lined_up_position` has a literal `"NA"` | **Yes**, exactly 1,383 rows |
| 13 prospects never took an NFL snap | **Yes**, 497 of 510 appear in `player_play` |
| BALL frames: 551 events, 54 players | **Exact.** 32,095 BALL rows · 551 events · 54 players (37 WR, 16 TE, 1 FB) |

## 🔴 New — found only by auditing the real files

### Every numeric column in `combine_results` ships as a string

`forty`, `ten_yd_split`, `vertical`, `broad_jump`, `three_cone`, `short_shuttle`,
`bench_reps`, `ngs_college_production_score`, `ngs_final_score` and `combine_position`
all arrive as **String**, because missing values are the literal token `"NA"` and there
are **zero real nulls**. The same sentinel documented for `lined_up_position` runs through
the whole table.

This is a quiet, high-damage trap. pandas converts `"NA"` to NaN by default, so a pandas
user gets floats and never notices — while polars with `null_values=[""]` keeps the column
as text, and `df["forty"].mean()` either errors or silently does the wrong thing. Two
analysts on the same data get different answers.

`ingest.py` now maps `"NA"` to null **per column**, excluding `lined_up_position` where
the token carries real meaning (penalty killed the play before the snap). Verified after
the fix: `combine_results` has exactly one String column left (`combine_position`), and
all 1,383 literal `"NA"` values in `lined_up_position` survive.

### The gauntlet has no ball tracking

`GAUNTLET_DRILL` has **zero** BALL rows — in WR (200 attempts / 107 players), TE (81 / 41)
*or* DB (123 / 119). Ball tracking lives in the **route** drills instead
(`DAGGER_ROUTE_LEFT`, `COMEBACK_ROUTE_RIGHT`, `POST_CORNER_ROUTE_RIGHT`,
`SLOT_STRIKE_ROUTE_LEFT`, `GO_ROUTE_RIGHT`, …), and only for the 54 players above.

→ "Gauntlet speed-retention through the catch" is **not executable as specified**. A
route-drill variant exists but caps out at n = 54.

### Drill names collide on spelling

Two strings for the same drill, which silently halves the sample:

- `PASS_PRO-MIRROR_DRILL` (84 attempts) vs `PASS_PRO_MIRROR_DRILL` (37) — **hyphen vs underscore**
- `OVER_SHOULDER_ADJUST` vs `OVER_THE_SHOULDER_ADJUST`
- `LINE_DRILL` (167 / 85) vs `LINE` (50 / 33)
- `SPEED_OUT_ROUTE_LEFT` (87 / 76) vs `SPEED_OUT_LEFT` (37 / 31)

(`TERYL_AUSTIN_DRILL_1` and `_2` are genuinely different drills, not a collision.)

### `SKILL_DRILLS_LB` exists and is not in the published dictionary

6 drills, 4 players. Too small to use, but it breaks any code that enumerates the
documented `drill_type` list.

### Agility-drill opt-out is severe, and test-retest is thin

| Test | Missing | Tracking players | With ≥ 2 reps |
|---|---:|---:|---:|
| 40-yard dash | 86 / 510 (16.9%) | 418 | **375** |
| Three-cone | **330 / 510 (64.7%)** | 160 | **38** |
| Short shuttle | **309 / 510 (60.6%)** | 170 | **42** |
| Bench press | 318 / 510 (62.4%) | — | — |
| Vertical / broad | ~14–17% | — | — |

Nearly two-thirds of the cohort skipped the three-cone and the shuttle. More damaging:
**only 38 and 42 prospects have two tracked reps**, so reliability for those drills rests
on ~40 players. The 40 is the opposite — 375 players with ≥2 reps.

The DB skill drills are better: `BACK_PEDAL_AND_TRANSITION_45_DEGREE_REACTION` has 241
attempts across 122 players, i.e. roughly two reps each.

### Cohort composition — no QBs, and effectively no running backs

n = 510: **WR 106 · CB 60 · G 51 · T 50 · DT 47 · TE 42 · DE 36 · OLB 30 · SS 28 ·
FS 25 · C 20 · NT 5 · DB 5 · ILB 2 · FB 1 · MLB 1 · RB 1**

No quarterbacks and no specialists. **RB and FB are one player each**, so there is no
running-back analysis in this dataset. Linebackers total 33 (and only 4 ran LB drills).
Grouped: OL 121 · DB 118 · EDGE (DE+OLB) 66 · interior DL 52 · WR 106 · TE 42.

---

# Data quirks & host clarifications

Everything here is sourced from the Kaggle competition forum (captured 2026-10-10). **Host-confirmed**
items come from Tom Bliss (NFL, competition host) or Kaggle staff. Participant-reported items are
independent audits that we should **re-verify ourselves** on first ingest — but they are specific enough
to be worth trusting as hypotheses.

Status legend: ✅ host-confirmed · 🔍 participant-reported, verify · ❓ open with organizers

---

## Killers — these will silently corrupt an analysis

### 🔍 The 2024 back-pedal drill is truncated (cross-year contamination)

`BACK_PEDAL_AND_TRANSITION_45_DEGREE_REACTION` reps in **2024 stop before the break**.

- Median rep length: **6.0 s in 2024** vs **11.6 s in 2023**
- The braking phase is simply absent: median max deceleration **0.01 yd/s² (2024)** vs **3.6 yd/s² (2023)**
- Consequence: if you pool draft years, attempt-1 vs attempt-2 correlation of braking looks like
  **r = 0.80**; *within* each year it is **r ≈ 0**. The apparent reliability is entirely a between-year
  location shift.

**Handling:** a missing phase cannot be rescued by centering. Either drop the 2024 rep for this drill, or
restrict to a complete-phase subset, and report the sensitivity both ways. Do not represent an unrecorded
braking phase as a near-zero value.
*(Source: Kaggle discussion [747105](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747105), Yumeko.)*

### 🔍 2025 Combine tracking is a different export (quantization + speed shift)

- 2023 & 2024: `x` sits on a **1/60-yard grid**, `s` on a **1/300 yd/s grid**, for 100% of frames.
- 2025: almost no frames are quantized.
- Median peak speed in DB drills is **0.12 yd/s lower in 2025**.

**Handling:** center/standardize every drill metric **within (drill_name, draft_year)** before comparing
players across classes. Fit any such calibration on training data only — centering using a held-out draft
class's distribution turns leave-one-class-out CV into transductive evaluation. Also run a sensitivity
check that recomputes displacement-based features at a common resolution.
*(Source: discussion 747105.)*

### 🔴 In-game tracking has only the rookie cohort

Files 7–9 contain frames for the 510 cohort players and nobody else. **There is no defender, no ball, no
QB, no other 21 players.** Any feature of the form "distance to X" is impossible to compute directly;
it must come from the pre-computed `player_play` NGS columns.
*(Source: Data tab — "tracks all 510 rookie cohort prospects".)*

---

### 🔍 Tracking-derived 40 times run ~0.3 s slow, and `dis` under-counts

Two measurement facts that will quietly break any attempt to reproduce the official
numbers from the trace:

- A 40-yard dash reconstructed from the tracking frames comes out roughly **0.3 s slower**
  than `combine_results.forty` (though the two correlate ~0.91). The electronic clock
  starts on first movement; the tracked window does not.
- **`dis` is unreliable as a distance measure** — it sums to about **37 yd over a 40-yard
  dash**, a ~7% under-count.

**Handling:** never present a tracking-derived drill time as "the 40 time", and never use
`dis` for path length. Integrate `hypot(diff(x), diff(y))` from the smoothed trajectory
instead (`kinematics.derivatives` → `path_length_yd`). Report the offset explicitly if
tracked and official times are ever shown together — a judge who knows this and sees it
unmentioned will assume the rest is equally unchecked.

### ⚠️ Nyquist: the textbook biomechanics cutoff is unavailable at 10 Hz

Sampling at 10 Hz puts Nyquist at **5 Hz**, so Winter's 6–7 Hz biomechanics cutoff — which
assumes 100–240 Hz motion capture — is mathematically out of reach. The usable band is
roughly **1.0–2.5 Hz**. Saying "we used a 6 Hz Butterworth, standard in biomechanics" on
this data is an instant credibility loss with an NFL analytics panel.

Cutoff choice is **use-case dependent**, and it dominates filter order (order 2 vs 4
differ by 0.1%). From a Monte-Carlo bake-off against analytic ground truth, peak-|a| bias:
raw central differences **+27.1%**, fc=2.5 +9.1%, **fc=2.0 +3.2%**, savgol(7,3) −2.4%,
fc=1.5 −6.0%, fc=1.0 −17.8%, savgol(11,3) −22.6%. Acceleration RMSE instead favours
fc=1.5.

→ `kinematics.CUTOFF_FOR_PEAKS = 2.0` when the feature *is* a peak (peak decel, max
curvature, min turn radius); `CUTOFF_FOR_TRACES = 1.5` for integrals and event timing.
Report a sensitivity sweep.

### ⚠️ `filtfilt` silently fails on short series — and dropping them biases the sample

`padlen = 3 * (2*order + 1)`, so an order-2 zero-phase Butterworth needs **≥ 16 frames
(1.6 s)** and order 4 needs ≥ 28. Plenty of play-player segments are shorter. Silently
dropping them biases the sample toward long developing plays, which is fatal for any claim
about explosiveness. `kinematics.smooth_xy` falls back to Savitzky-Golay instead of
dropping, and `return_method=True` reports which filter actually ran so the choice can be
carried into the feature table as a column.

### DuckDB's default CSV sample is 20,480 rows

If you read these CSVs with DuckDB rather than the project's polars path, pass
`sample_size=-1`. The default is exactly how `event` (mostly empty) and
`draft_overall_pick` (null for every UDFA) get their types mis-inferred.

---

## Context worth knowing

**2023–2025 is the complete history of NFL Combine sensor tracking.** There is no fourth
year and no prior corpus anyone could have mined. Every finding from this data is
first-generation — which is also why the published literature is silent on movement
quality as opposed to drill times.

**The incumbent model is monotonically constrained.** The NGS draft model is a
position-specific XGBoost across 12 positions **with monotonic constraints**, trained on
Combine results since 2003 and college stats since 2005, predicting the likelihood a
player becomes an NFL starter or Pro Bowler within three seasons, output on a 50–99 scale.
A monotone model structurally **cannot represent an optimum** — it cannot encode "too much
of this is bad". Any genuine inverted-U relationship in the tracking data is therefore a
named structural edge over the incumbent, not just a different fit.

**Submission mechanics that zero a submission:** notebook left private; writeup left in
draft at the deadline; no Media Gallery cover image; over 2,000 words; 10 or more figures;
or a notebook that does not touch the tracking data.

---

## Null / sentinel semantics

### ✅ Pass-rush nulls (Tom Bliss)

- `quick_pressure` / `time_to_pressure` **NA while `blitzing` is TRUE ⇒ there was no pressure.**
- `quick_pressure == FALSE` ⇒ **a pressure did occur**, but it was not "quick" (not within 2.50 s).
  → Never treat `quick_pressure` as a clean 0/1 indicator of pressure; `FALSE` and `NA` mean *opposite*
  things.
- `player_get_off` is NA if the player never crossed the line of scrimmage (rare).
- `blitzing == TRUE` always implies the player was rushing the passer.
- To build the **denominator of pass-rush opportunities**, filter `pass_result != ""` — that selects every
  play on which the QB dropped back.
*(Source: discussion [746678](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/746678).)*

### ✅ `lined_up_position == "NA"` is a literal string, not a null

1,383 rows. These are plays killed by a penalty before the snap, so no alignment exists.
**pandas will silently convert `"NA"` to NaN** unless you pass `keep_default_na=False` or an explicit
`na_values` list. Decide deliberately which you want.
*(Reported in discussion [747108](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747108); host confirmed the cause.)*

### ✅ Missing `attempt` numbers are intentional

If a prospect has only attempt 2 of the 40, attempt 1 had a data problem and was excluded — it was not
"aborted" in a way that carries signal. Do not impute it.
*(Source: discussion [747187](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747187).)*

### ✅ `nfl_id` on BALL frames

The published dictionary said "null for BALL frames". It was **wrong and has been corrected**: on a BALL
row, `nfl_id` is the id of the athlete performing that drill. Filter `entity_type == "PLAYER"` before any
athlete-movement computation.
*(Source: discussion 747108, Tom Bliss.)*

---

## Cohort coverage

### ✅ 13 of the 510 players never took an NFL snap

`player_play.csv` covers **497 of 510 players** and **1,001 of 1,002 games**. The 13 missing players
"did not ever make it to the field."

Tom Bliss explicitly flags this as **analytically interesting, not as dirt**:

> "You could use this information as part of your analysis (i.e. perhaps their combine performance led to
> them never receiving the opportunity) or focus on those who do have on field plays."

→ This is a free, host-endorsed hook for a **selection / survivorship** component. The 13 are the only
truly censored observations; the rest are censored by *degree* of opportunity.

### 🔍 Join exceptions between tracking and `player_play`

Collapsing game tracking to unique `(game_id, play_id, nfl_id)`:

| | 2023 | 2024 | 2025 | total |
|---|---:|---:|---:|---:|
| Tracking keys with **no** `player_play` row | 449 | 857 | 1,191 | **2,497** |
| `player_play` rows with **no** tracking | 293 | 661 | 796 | **1,750** |

The 2,497 unmatched tracking keys concentrate in **WR (1,760), TE (721), FB (16)**; 2,233 REG / 79 POST /
185 PRE. For 2,288 of them another player on the same game/play *is* present in `player_play`; for 209 the
whole game/play pair is absent. No null or duplicate tracking composite keys, no orphan player or game ids.

**Handling:** audit both sides of the join, keep an explicit exception table, report cohort coverage before
filtering to complete cases, and never fill missing context with zero.
*(Source: discussion [747584](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747584), Muhammad Jawad1984. ❓ unanswered by organizers as of 2026-10-10.)*

### 🔍 Row counts disagree with the Data tab

See the table at the end of `docs/data-dictionary.md`. Two independent downloads were byte-identical
(SHA256), and pandas and `csv.reader` agree, so the **files are right and the published counts are stale**.
Curiously the *file sizes* on the Data tab match. ❓ unanswered.

---

## Scope clarifications from the host

- ✅ **Preseason and postseason plays may be used** as supporting outcomes, even though the theme says
  "regular-season". *(discussion [746425](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/746425).)*
- ✅ Word/figure limits apply to the **writeup only**; an appendix inside the writeup and the attached
  notebook do not count. *(746425.)*
- ✅ **No prediction/leaderboard competition this year.** *(discussion [746521](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/746521).)*
- ✅ **AI coding assistants and private cloud workspaces are allowed.** *(discussion [747086](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747086), Paul Mooney.)*
- ✅ Submissions must be **Writeups with an attached public notebook** — a forum post is not a submission.
  *(discussion [747098](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747098), Paul Mooney.)*

---

## Public resources other participants have shared

| What | Where | Use |
|---|---|---|
| DB drills EDA — all 8 DB drills, CB vs S, repeatability, the 2024 data trap | [kaggle.com/code/yumekohata/db-drills-decoded-cb-s-tracking-2024-data-trap](https://www.kaggle.com/code/yumekohata/db-drills-decoded-cb-s-tracking-2024-data-trap) | Best public EDA so far; the source of the 2024/2025 export findings |
| Pre-draft college features for all 510 prospects (CFBD + RAS percentiles, temporally strict) | [kaggle.com/datasets/angelojun2k/nfl-bdb2027-predraft-college-features](https://www.kaggle.com/datasets/angelojun2k/nfl-bdb2027-predraft-college-features) | Free external covariates; CC BY-NC 4.0. **Audit before trusting.** |

## Angles already staked out publicly (as of 2026-10-10)

- **WR Gauntlet drill → in-game peak speed**, residualized on 40 time and weight, LODO CV, "Hidden Movers"
  4-quadrant archetype matrix *(Oriol Pi Morell, discussion 747098)*.
- **DB drills repeatability / CB vs S movement profiling** *(Yumeko, discussion 747105)*.
- Generic "physics-informed combine metrics + multi-factor scoring framework" posts.

Avoid colliding head-on with these; see `docs/plan.md`.
