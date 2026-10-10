# NFL Big Data Bowl 2027 — Combine tracking → NFL performance

Working repo for the [NFL Big Data Bowl 2027](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027)
hackathon: linking **10 Hz NFL Scouting Combine sensor tracking** to **regular-season NFL
game performance**.

**This is a judged hackathon, not a leaderboard competition.** There is no metric and no
`submission.csv`. The deliverable is a **Kaggle Writeup of ≤ 2,000 words with < 10
figures**, plus an attached **public Kaggle Notebook**, judged by analytics staff from the
32 NFL teams. Deadline **2027-01-06**. Full details in
[`docs/competition-brief.md`](docs/competition-brief.md).

## Start here

| Document | What it is |
|---|---|
| [`docs/competition-brief.md`](docs/competition-brief.md) | Rules, timeline, prizes, the scoring rubric, and what the host said to do |
| [`docs/data-dictionary.md`](docs/data-dictionary.md) | All 9 files, 158 columns, annotated where the shipped data disagrees with the published dictionary |
| [`docs/data-quirks.md`](docs/data-quirks.md) | **Read before modelling.** Host clarifications and the traps that will silently corrupt an analysis |
| [`docs/research-brief.md`](docs/research-brief.md) | Prior art, candidate research questions, methodology |
| [`docs/plan.md`](docs/plan.md) | The attack plan and current status |
| `reports/data_audit.md` | Generated: every data claim re-derived from the shipped files |

## Quick start

```bash
make setup                 # .venv + dependencies
make data                  # download from Kaggle (needs a token; see below)
make parquet               # CSV -> zstd parquet, once
make audit                 # -> reports/data_audit.md
```

No competition data yet? The whole pipeline runs on synthetic fixtures that reproduce the
real schema *and* the known quirks:

```bash
python tests/make_fixtures.py --out data/fixtures
mkdir -p data/_fixture_run && ln -sfn "$PWD/data/fixtures" data/_fixture_run/raw
export NFLBDB_DATA="$PWD/data/_fixture_run"
python scripts/01_build_parquet.py && python scripts/00_audit_raw.py
python scripts/90_figure_demo.py          # -> reports/figures/drill_anatomy_light.png
```

### Getting the data

The data is **CC BY-NC 4.0 and must not be redistributed**, so `data/` is gitignored.

1. Sign in to Kaggle and **join the hackathon** (the API returns 403 until the rules are
   accepted): <https://www.kaggle.com/competitions/nfl-big-data-bowl-2027>
2. Authenticate: `.venv/bin/kaggle auth login` (OAuth, nothing to manage), or put an API
   token at `~/.kaggle/kaggle.json`.
3. `make data` — ~2.3 GB into `data/raw/`.

## Layout

```
docs/          competition brief, data dictionary, quirks, research brief, plan
src/nflbdb/    the library
  config.py            paths, file map, drill vocabulary, known-bad drill/years
  ingest.py            CSV -> parquet streaming, lazy loaders
  kinematics.py        smoothing, derivatives, curvature, cut detection, sprint profiling
  combine_features.py  per-attempt movement features from drill trajectories
  reliability.py       ICC, test-retest, attenuation ceilings
  modeling.py          draft-capital controls, residualization, leave-one-class-out CV
  viz.py               the figure system (validated palette, field + drill canvases)
scripts/       00_audit_raw · 01_build_parquet · 90_figure_demo
notebooks/     exploration
tests/         make_fixtures.py — synthetic stand-in for the real data
reports/       generated audit + figures
```

## Design decisions worth knowing

**Features come from the raw trajectory, not the vendor columns.** The shipped `s` and
`a` are smoothed with an undocumented filter; `a` in particular is noisy enough that a
naive "max deceleration" mostly measures noise. `kinematics.py` re-derives velocity and
acceleration from `(t, x, y)` with an explicit 2 Hz zero-phase Butterworth filter, and
keeps the vendor columns alongside as a cross-check.

**Acceleration is split into tangential and normal components.** `a_tan` is pure speed
change — it is what "deceleration into a break" and "burst out of a cut" actually mean.
`a_norm` is the lateral force needed to turn. A single `|a|` conflates them.

**Turn radius is undefined for a reversal.** When an athlete retraces his own line the
velocity and acceleration vectors are parallel, curvature → 0, and `1/κ` → ∞ — which
would rank the sharpest move in football as the gentlest. The 5-10-5 short shuttle is
built out of exactly this move, so reversals report `NaN` for radius and are described by
lateral excursion instead.

**Every drill metric is standardized within `(drill_name, draft_year)`.** The 2025
Combine export is not quantized like 2023/2024 and shows a systematic speed offset, so a
raw cross-class comparison partly measures the vendor's export pipeline.

**Reliability before validity.** Many drills have two reps per prospect, which is a
ready-made test-retest design. A metric's correlation with any outcome is capped at
`sqrt(reliability)`, so `reliability.py` reports that ceiling next to every finding.

**Draft position is both confounder and mediator.** Teams saw the same Combine data, so
draft slot is downstream of Combine performance and upstream of opportunity. The honest
framing is *incremental* value over a draft-capital baseline, which is what
`modeling.py` is built around.

## Licence

Code: MIT. Competition data: CC BY-NC 4.0, not redistributed here.
