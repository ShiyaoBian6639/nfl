#!/usr/bin/env python
"""Convert every raw CSV to zstd parquet once, so nothing downstream parses CSV again.

    python scripts/01_build_parquet.py [--overwrite]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nflbdb import ingest
from nflbdb.config import INTERIM, RAW


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    if not any(RAW.glob("*.csv")):
        print(f"No CSVs in {RAW}. Run scripts/download_data.sh first.", file=sys.stderr)
        return 1

    print(f"raw:     {RAW}")
    print(f"interim: {INTERIM}\n")
    reports = ingest.convert_all(overwrite=args.overwrite)

    converted = [r for r in reports if r["status"] == "converted"]
    if converted:
        print(f"\ntotal: {sum(r['rows'] for r in converted):,} rows, "
              f"{sum(r['csv_mb'] for r in converted):.0f} MB csv -> "
              f"{sum(r['parquet_mb'] for r in converted):.0f} MB parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
