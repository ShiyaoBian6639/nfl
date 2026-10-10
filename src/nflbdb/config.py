"""Paths, dataset constants and football-domain vocabulary.

Everything that is "a fact about the dataset" lives here so that the rest of the
code never hard-codes a filename, a column name or a drill string.
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]

DATA = Path(os.environ.get("NFLBDB_DATA", ROOT / "data"))
RAW = DATA / "raw"          # untouched Kaggle CSVs (gitignored)
INTERIM = DATA / "interim"  # parquet mirrors of the CSVs (gitignored)
PROCESSED = DATA / "processed"  # feature tables (gitignored)

REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
DOCS = ROOT / "docs"

for _p in (RAW, INTERIM, PROCESSED, FIGURES):
    _p.mkdir(parents=True, exist_ok=True)

COMPETITION = "nfl-big-data-bowl-2027"

# --------------------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------------------

#: logical name -> csv filename
FILES: dict[str, str] = {
    "players": "players.csv",
    "combine_results": "combine_results.csv",
    "combine_tracking": "combine_tracking.csv",
    "player_career_successes": "player_career_successes.csv",
    "player_play": "player_play.csv",
    "games": "games.csv",
    "game_tracking_2023": "game_tracking_2023.csv",
    "game_tracking_2024": "game_tracking_2024.csv",
    "game_tracking_2025": "game_tracking_2025.csv",
}

GAME_TRACKING = ("game_tracking_2023", "game_tracking_2024", "game_tracking_2025")

#: Row counts advertised on the Kaggle Data tab. The shipped files disagree for several
#: files (see docs/data-quirks.md); scripts/00_audit_raw.py records what is actually there.
ADVERTISED_ROWS: dict[str, int] = {
    "players": 510,
    "games": 1_002,
    "player_play": 316_338,
    "game_tracking_2023": 1_421_805,
    "game_tracking_2024": 3_042_118,
    "game_tracking_2025": 4_339_021,
}

#: Counts independently reported on the competition forum for the distributed files.
FORUM_REPORTED_ROWS: dict[str, int] = {
    "combine_tracking": 463_189,
    "player_play": 314_197,
    "game_tracking_2023": 3_665_443,
    "game_tracking_2024": 7_827_944,
    "game_tracking_2025": 11_160_903,
}

# --------------------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------------------

PLAYER_KEY = ("nfl_id",)
PLAY_KEY = ("game_id", "play_id")
PLAYER_PLAY_KEY = ("game_id", "play_id", "nfl_id")
FRAME_KEY = ("game_id", "play_id", "nfl_id", "time")
COMBINE_ATTEMPT_KEY = ("nfl_id", "drill_name", "attempt")

# --------------------------------------------------------------------------------------
# Field geometry (yards)
# --------------------------------------------------------------------------------------

FIELD_LENGTH = 120.0   # including both 10-yard end zones
FIELD_WIDTH = 53.3333
ENDZONE = 10.0
HASH_FROM_SIDELINE = 23.5833  # NFL hash marks

SAMPLE_HZ = 10.0
DT = 1.0 / SAMPLE_HZ

# --------------------------------------------------------------------------------------
# Combine drills
# --------------------------------------------------------------------------------------

STANDARDIZED_DRILLS = ("FORTY_YARD_DASH", "THREE_CONE_DRILL", "SHORT_SHUTTLE")

SKILL_DRILL_TYPES = (
    "SKILL_DRILLS_WR",
    "SKILL_DRILLS_TE",
    "SKILL_DRILLS_DB",
    "SKILL_DRILLS_OL",
    "SKILL_DRILLS_DL",
)

#: Drill/year combinations known to be unusable. See docs/data-quirks.md.
#: 2024 back-pedal reps stop before the break, so every braking feature is absent
#: (median max deceleration 0.01 vs 3.6 yd/s^2 in 2023).
SUSPECT_DRILL_YEARS: tuple[tuple[str, int], ...] = (
    ("BACK_PEDAL_AND_TRANSITION_45_DEGREE_REACTION", 2024),
)

#: 2023/2024 Combine exports are quantized; 2025 is not. Always standardize within
#: (drill_name, draft_year) before comparing prospects across classes.
QUANTIZED_YEARS = (2023, 2024)
X_QUANTUM = 1.0 / 60.0      # yards
S_QUANTUM = 1.0 / 300.0     # yd/s

# --------------------------------------------------------------------------------------
# Position vocabulary
# --------------------------------------------------------------------------------------

POSITION_GROUPS: dict[str, tuple[str, ...]] = {
    "QB": ("QB",),
    "RB": ("RB", "FB"),
    "WR": ("WR",),
    "TE": ("TE",),
    "OL": ("T", "G", "C"),
    "DL": ("DE", "DT", "NT"),
    "EDGE": ("DE", "OLB"),
    "LB": ("ILB", "MLB", "OLB"),
    "CB": ("CB", "DB"),
    "S": ("SS", "FS"),
}

#: inverse lookup, first match wins for ambiguous positions (OLB, DB)
POSITION_TO_GROUP: dict[str, str] = {}
for _g, _ps in POSITION_GROUPS.items():
    for _p in _ps:
        POSITION_TO_GROUP.setdefault(_p, _g)

# --------------------------------------------------------------------------------------
# Sentinels
# --------------------------------------------------------------------------------------

#: player_play.lined_up_position uses the literal string "NA" for penalty-killed plays.
#: Pass keep_default_na=False (pandas) or null_values=[] (polars) and handle explicitly.
LITERAL_NA_COLUMNS = ("lined_up_position",)
