#!/bin/bash
# Build + encrypt the SOW26 site.
#   ./build.sh            — build both pages from src/ into encrypted root files
# Password comes from $SOW26_PASSWORD (never committed). Salt is fixed so that
# previously-remembered devices stay unlocked and one unlock covers all pages.
set -euo pipefail
cd "$(dirname "$0")"

: "${SOW26_PASSWORD:?Set SOW26_PASSWORD env var}"
SALT="923a427110851e511766b824206373c5"
TITLE="Toivosten kopla × SOW 2026"
INSTR="Salasana löytyy perheen WhatsApp-ryhmästä 🧭"

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

# 1. briefing: inject teaser + stage chips from data
python3 pipeline/inline_briefing.py src/index.html "$BUILD_DIR/index.html"

# 2. kisatori: inject data payload (JSON + crops as data URIs)
python3 pipeline/inline_data.py src/kisatori.html "$BUILD_DIR/kisatori.html"

# 3. encrypt both with the shared salt + password
for f in index kisatori; do
  npx -y staticrypt "$BUILD_DIR/$f.html" -p "$SOW26_PASSWORD" --salt "$SALT" \
    -d "$BUILD_DIR/out" --short \
    --template-title "$TITLE" --template-instructions "$INSTR" --template-button "Avaa" \
    >/dev/null
done

# 4. install at repo root (kisatori as a directory for a clean URL)
cp "$BUILD_DIR/out/index.html" index.html
mkdir -p kisatori
cp "$BUILD_DIR/out/kisatori.html" kisatori/index.html

# 5. sanity: encrypted output must not leak plaintext
for f in index.html kisatori/index.html; do
  grep -q staticrypt "$f" || { echo "FAIL: $f not encrypted"; exit 1; }
  if grep -q "Toivonen Vilhelm\|sec-head\|KISATORI_DATA" "$f"; then
    echo "FAIL: $f contains plaintext"; exit 1
  fi
done
echo "OK: built index.html + kisatori/index.html (encrypted)"
