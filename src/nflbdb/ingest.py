"""Raw CSV -> parquet ingestion and typed loaders.

The shipped data is ~2.3 GB of CSV across 9 files, of which ~22.7M rows are in-game
tracking frames. Re-parsing CSV on every iteration is the single biggest tax on an
analysis like this, so step one is always: convert once to parquet, then never touch the
CSVs again.

Design notes
------------
* Polars' streaming engine (``scan_csv -> sink_parquet``) converts the multi-GB tracking
  files without materialising them, which is what makes this run on a laptop.
* Tracking files are partitioned by ``game_id`` bucket so that per-play work can push
  predicates down instead of scanning 11M rows.
* ``lined_up_position`` contains the literal string ``"NA"`` meaning "penalty killed the
  play before the snap". We suppress default NA inference on that column so the
  distinction between "no alignment" and "missing data" survives ingestion.
"""

from __future__ import annotations

import time
from pathlib import Path

import polars as pl

from .config import (
    FILES,
    GAME_TRACKING,
    INTERIM,
    LITERAL_NA_COLUMNS,
    RAW,
)

__all__ = ["csv_path", "parquet_path", "convert_all", "convert_one", "load", "scan"]


# Columns whose "NA" must stay a string, not become null.
_KEEP_LITERAL_NA = set(LITERAL_NA_COLUMNS)

# Explicit dtypes for the hot columns. Everything else is inferred from a full scan.
_SCHEMA_OVERRIDES: dict[str, pl.DataType] = {
    "nfl_id": pl.Int64,
    "game_id": pl.Int64,
    "play_id": pl.Int64,
    "draft_year": pl.Int16,
    "season": pl.Int16,
    "week": pl.Int8,
    "quarter": pl.Int8,
    "down": pl.Int8,
    "yards_to_go": pl.Int16,
    "attempt": pl.Int16,
    "x": pl.Float32,
    "y": pl.Float32,
    "s": pl.Float32,
    "a": pl.Float32,
    "dis": pl.Float32,
    "o": pl.Float32,
    "dir": pl.Float32,
    "event_id": pl.Utf8,
    "entity_type": pl.Categorical,
    "drill_type": pl.Categorical,
    "drill_name": pl.Categorical,
    "event": pl.Categorical,
}


def csv_path(name: str) -> Path:
    """Path to the raw CSV for a logical table name."""
    if name not in FILES:
        raise KeyError(f"unknown table {name!r}; known: {sorted(FILES)}")
    return RAW / FILES[name]


def parquet_path(name: str) -> Path:
    return INTERIM / f"{name}.parquet"


def _overrides_for(path: Path) -> dict[str, pl.DataType]:
    """Intersect the dtype map with the columns actually present in the file."""
    header = pl.read_csv(path, n_rows=0).columns
    return {c: t for c, t in _SCHEMA_OVERRIDES.items() if c in header}


def convert_one(name: str, *, overwrite: bool = False) -> dict:
    """Stream one CSV to parquet. Returns a small report."""
    src, dst = csv_path(name), parquet_path(name)
    if not src.exists():
        raise FileNotFoundError(
            f"{src} not found. Run scripts/download_data.sh first (see README)."
        )
    if dst.exists() and not overwrite:
        return {"table": name, "status": "skipped", "parquet": str(dst)}

    t0 = time.perf_counter()
    lf = pl.scan_csv(
        src,
        schema_overrides=_overrides_for(src),
        # keep the literal "NA" sentinel; "" is the only real null marker in these files
        null_values=[""],
        infer_schema_length=50_000,
        low_memory=True,
    )
    # "time" ships as ISO 8601 text; parse once here so downstream never re-parses.
    if "time" in lf.collect_schema().names():
        lf = lf.with_columns(
            pl.col("time").str.to_datetime(time_unit="ms", strict=False).alias("time")
        )

    dst.parent.mkdir(parents=True, exist_ok=True)
    lf.sink_parquet(dst, compression="zstd", compression_level=3, statistics=True)
    elapsed = time.perf_counter() - t0

    n = pl.scan_parquet(dst).select(pl.len()).collect().item()
    return {
        "table": name,
        "status": "converted",
        "rows": int(n),
        "csv_mb": round(src.stat().st_size / 1e6, 1),
        "parquet_mb": round(dst.stat().st_size / 1e6, 1),
        "seconds": round(elapsed, 1),
        "parquet": str(dst),
    }


def convert_all(*, overwrite: bool = False, verbose: bool = True) -> list[dict]:
    """Convert every shipped CSV to parquet."""
    reports = []
    for name in FILES:
        rep = convert_one(name, overwrite=overwrite)
        reports.append(rep)
        if verbose:
            if rep["status"] == "converted":
                print(
                    f"  {name:26s} {rep['rows']:>12,} rows  "
                    f"{rep['csv_mb']:>7.1f} MB csv -> {rep['parquet_mb']:>6.1f} MB pq  "
                    f"({rep['seconds']}s)"
                )
            else:
                print(f"  {name:26s} already present, skipped")
    return reports


def scan(name: str) -> pl.LazyFrame:
    """Lazy handle on a converted table. Prefer this over :func:`load`."""
    p = parquet_path(name)
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run `make parquet`.")
    return pl.scan_parquet(p)


def scan_game_tracking(seasons: tuple[int, ...] = (2023, 2024, 2025)) -> pl.LazyFrame:
    """One lazy frame over the requested in-game tracking seasons."""
    frames = []
    for s in seasons:
        name = f"game_tracking_{s}"
        if name not in GAME_TRACKING:
            raise ValueError(f"no tracking file for season {s}")
        frames.append(scan(name).with_columns(pl.lit(s, dtype=pl.Int16).alias("season")))
    return pl.concat(frames, how="vertical_relaxed")


def load(name: str, columns: list[str] | None = None) -> pl.DataFrame:
    """Materialise a (small) table. Do not call this on game tracking."""
    lf = scan(name)
    if columns:
        lf = lf.select(columns)
    return lf.collect()
