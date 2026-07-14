#!/usr/bin/env bash
# Re-fetch trackmaxx for one stage and recompute all outputs.
# Usage: pipeline/build_stage.sh <stage-number>
# Compute always recomputes every stage internally (cross-stage standings,
# forecast, badges need all three) but only rewrites data/stage<N>.json for the
# requested stage; forecast/badges/crops are always refreshed. Any Livelox files
# present in data/livelox/ are picked up automatically.
set -euo pipefail
STAGE="${1:?usage: build_stage.sh <stage>}"
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"
cd "$DIR"
echo "[build_stage] fetching trackmaxx stage $STAGE ..."
"$PY" -c "import lib_trackmaxx as T; T.fetch_stage($STAGE)"
echo "[build_stage] computing ..."
"$PY" compute.py --stages "$STAGE"
