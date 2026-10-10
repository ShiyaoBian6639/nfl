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
