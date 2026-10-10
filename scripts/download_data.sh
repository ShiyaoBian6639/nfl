#!/usr/bin/env bash
# Download the NFL Big Data Bowl 2027 competition data (~2.3 GB) into data/raw/.
#
# Prerequisites
#   1. A Kaggle account that has JOINED the hackathon:
#        https://www.kaggle.com/competitions/nfl-big-data-bowl-2027  -> "Join Hackathon"
#      (You must accept the rules; the API returns 403 until you do.)
#   2. An API token: Kaggle -> Settings -> API -> "Create New Token" downloads kaggle.json
#        mkdir -p ~/.kaggle && mv ~/Downloads/kaggle.json ~/.kaggle/ && chmod 600 ~/.kaggle/kaggle.json
#      Or export KAGGLE_USERNAME / KAGGLE_KEY.
#
# The data is CC BY-NC 4.0 and must not be redistributed. data/ is gitignored.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAW="${ROOT}/data/raw"
COMP="nfl-big-data-bowl-2027"

KAGGLE_BIN="${ROOT}/.venv/bin/kaggle"
[[ -x "$KAGGLE_BIN" ]] || KAGGLE_BIN="$(command -v kaggle || true)"

if [[ -z "$KAGGLE_BIN" ]]; then
  echo "ERROR: kaggle CLI not found. Install deps first:  make setup" >&2
  exit 1
fi

if [[ ! -f "${HOME}/.kaggle/kaggle.json" && -z "${KAGGLE_KEY:-}" ]]; then
  cat >&2 <<'MSG'
ERROR: no Kaggle credentials found.

  1. Sign in at https://www.kaggle.com and JOIN the hackathon:
       https://www.kaggle.com/competitions/nfl-big-data-bowl-2027
  2. https://www.kaggle.com/settings -> API -> "Create New Token"
  3. mkdir -p ~/.kaggle && mv ~/Downloads/kaggle.json ~/.kaggle/ && chmod 600 ~/.kaggle/kaggle.json
MSG
  exit 1
fi

mkdir -p "$RAW"
echo "==> downloading ${COMP} into ${RAW} (~2.3 GB)"
"$KAGGLE_BIN" competitions download -c "$COMP" -p "$RAW"

ZIP="${RAW}/${COMP}.zip"
if [[ -f "$ZIP" ]]; then
  echo "==> unzipping"
  unzip -o -q "$ZIP" -d "$RAW"
  echo "==> recording checksum before removing the archive"
  shasum -a 256 "$ZIP" | tee "${RAW}/.zip.sha256"
  rm -f "$ZIP"
fi

echo "==> done"
ls -lh "$RAW"
