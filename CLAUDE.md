# Working notes for this repo

## What this project is

A submission to the **NFL Big Data Bowl 2027** — a *judged hackathon*, not a leaderboard
competition. Deliverable: a Kaggle Writeup, ≤ 2,000 words, < 10 figures, plus a public
Kaggle Notebook. Judged 30% football value / 30% data science / 20% writing / 20% data
visualization by NFL team analytics staff. Deadline 2027-01-06.

Read `docs/competition-brief.md`, `docs/data-dictionary.md` and `docs/data-quirks.md`
before touching analysis code. `docs/plan.md` holds current status and open decisions.

## Conventions

- Python 3.12 in `.venv`. `polars` for data, `matplotlib` for figures. Run things through
  `make`; scripts assume `PYTHONPATH=src`.
- `NFLBDB_DATA` overrides the data root — that is how the fixture runs work. Never write
  to `data/raw/`.
- **Never commit competition data.** CC BY-NC 4.0 forbids redistribution; `data/` is
  gitignored, and so is `*.csv` / `*.parquet` globally.
- All figures go through `src/nflbdb/viz.py` so the submission reads as one visual
  system. The palette is CVD-validated in fixed slot order — do not cycle hues, do not
  add a 9th series, never build a dual-axis chart.
- New data claims get a check in `scripts/00_audit_raw.py` rather than a comment. The
  audit report is the project's shared source of truth about the data.

## Non-obvious traps already handled

These are easy to reintroduce. See `docs/data-quirks.md` for sources.

1. **2024 back-pedal reps are truncated** before the break. Pooling draft years makes
   braking reliability look like r = 0.80 when within-year it is ≈ 0. Listed in
   `config.SUSPECT_DRILL_YEARS` and dropped by default.
2. **2025 Combine tracking is a different export** — unquantized coordinates, lower
   median peak speed. Always standardize within `(drill_name, draft_year)`, and fit that
   centering on training folds only or LODO CV becomes transductive.
3. **In-game tracking contains only the 510 rookie-cohort players.** No defenders, no
   ball, no QB. "Distance to nearest defender" is not computable; it must come from the
   pre-computed `player_play` NGS columns.
4. **`quick_pressure == FALSE` and `NA` mean opposite things.** NA with `blitzing` true
   means no pressure; FALSE means a pressure that was not quick.
5. **`lined_up_position` uses the literal string `"NA"`** for penalty-killed plays.
   pandas converts it to NaN unless told otherwise.
6. **Missing `attempt` numbers are deliberate** — that attempt had a data problem. Do not
   impute.
7. **Turn radius is degenerate on a 180° reversal.** Handled in `kinematics.detect_cuts`.

## Testing

There is no real data in CI. `tests/make_fixtures.py` generates a synthetic stand-in with
the same schema *and* the same quirks, so the pipeline is exercisable end to end:

```bash
python tests/make_fixtures.py --out data/fixtures
export NFLBDB_DATA="$PWD/data/_fixture_run"   # with data/_fixture_run/raw -> data/fixtures
python scripts/01_build_parquet.py --overwrite && python scripts/00_audit_raw.py
```

Fixture numbers are not meaningful — they test plumbing, not football.
